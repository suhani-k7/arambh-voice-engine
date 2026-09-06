import asyncio
import re
from core.conversation_state import ConversationState, ConversationStage, BorrowerProfile
from core.interfaces import LLMHandler, ExtractorHandler, StorageHandler
from factories.extractor_factory import get_extractor_handler
from factories.storage_factory import get_storage_handler
from utils.latency import timed_stage
from utils.logger import AppLogger

logger = AppLogger.get_instance()

LLM_RESPONSE_TIMEOUT_SECONDS = 10.0
LLM_TIMEOUT_FALLBACK_REPLY = "I'm sorry, I didn't quite catch that. Could you please repeat what you said?"

class ConversationEngine:

    def __init__(
        self,
        llm: LLMHandler,
        call_sid: str,
        extractor: ExtractorHandler | None = None,
        storage: StorageHandler | None = None,
    ):
        self._llm = llm
        self._extractor = extractor or get_extractor_handler()
        self._storage = storage or get_storage_handler()
        self.state = ConversationState(call_sid=call_sid)

    async def process_transcript(self, text: str, is_final: bool) -> str | None:
        """
        Called whenever a transcript comes in.
        Returns the agent's response text, or None if waiting for more speech.
        """
        if not is_final:
            return None  # wait for complete utterance

        if not text.strip():
            return None

        self.state.add_user_message(text)
        self._extract_borrower_info(text)

        # Build messages for LLM (only standard role and content fields)

        stage_hint = f"\n[Context: stage={self.state.stage.value}, missing={self.state.borrower.missing_fields()}]"
        
        messages_for_llm = []
        for idx, msg in enumerate(self.state.history):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            # Append context hint to the latest user message
            if idx == len(self.state.history) - 1 and role == "user":
                content = f"{content} {stage_hint}"
            messages_for_llm.append({"role": role, "content": content})

        async with timed_stage(self.state.call_sid, "llm_response"):
            try:
                response = await asyncio.wait_for(
                    self._llm.get_response(messages_for_llm), timeout=LLM_RESPONSE_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                logger.error(
                    "LLM response timed out after %.1fs | call_sid: %s",
                    LLM_RESPONSE_TIMEOUT_SECONDS, self.state.call_sid
                )
                response = LLM_TIMEOUT_FALLBACK_REPLY
        self.state.add_assistant_message(response)
        self._advance_stage_if_needed()

        return response


    def get_greeting(self) -> str:
        greeting = (
            "Hello! I'm Arambh, your loan onboarding assistant from Arambh Finance. "
            "I'd like to collect some basic information to get started. May I know your full name please?"
        )
        self.state.add_assistant_message(greeting)
        self.state.advance_stage()
        return greeting

    def _extract_borrower_info(self, text: str) -> None:
        """Heuristic / Regex extraction for fast real-time stage transitions."""
        text_clean = text.strip()
        text_lower = text_clean.lower()

        # 1. Extract Name (stripping common filler phrases)
        if not self.state.borrower.name and self.state.stage == ConversationStage.COLLECT_NAME:
            name_candidate = re.sub(
                r'^(my name is|i am|this is|mera naam|naam hai|myself)\s+',
                '',
                text_clean,
                flags=re.IGNORECASE
            ).strip()
            name_candidate = re.sub(r'[^\w\s]', '', name_candidate).strip()
            words = name_candidate.split()
            if 1 <= len(words) <= 4:
                self.state.borrower.name = name_candidate.title()
                logger.info("Extracted name (heuristic): %s", self.state.borrower.name)

        # 2. Extract Phone Number (10 digits, optional country code)
        if not self.state.borrower.phone:
            phone_match = re.search(r'(?:\+91[\-\s]?)?[6-9]\d{9}', text_clean)
            if phone_match:
                self.state.borrower.phone = phone_match.group(0).replace(" ", "").replace("-", "")
                logger.info("Extracted phone (heuristic): %s", self.state.borrower.phone)

        # 3. Extract Loan Amount
        if not self.state.borrower.loan_amount and self.state.stage in [
            ConversationStage.COLLECT_LOAN_AMT,
            ConversationStage.COLLECT_NAME
        ]:
            amount_match = re.search(r'(\d+(?:[.,]\d+)?)\s*(lakh|lakhs|lac|lacs|thousand|k|crore|cr)?', text_lower)
            if amount_match and any(char.isdigit() for char in amount_match.group(0)):
                matched_val = amount_match.group(0).strip()
                # Exclude if it looks like a phone number
                if len(matched_val) < 8 or "lakh" in matched_val or "lac" in matched_val or "thousand" in matched_val:
                    self.state.borrower.loan_amount = matched_val
                    logger.info("Extracted loan amount (heuristic): %s", self.state.borrower.loan_amount)

        # 4. Extract Monthly Income
        if not self.state.borrower.monthly_income and self.state.stage == ConversationStage.COLLECT_INCOME:
            income_match = re.search(r'(\d+(?:[.,]\d+)?)\s*(lakh|lakhs|lac|lacs|thousand|k|pm|per month)?', text_lower)
            if income_match:
                self.state.borrower.monthly_income = income_match.group(0).strip()
                logger.info("Extracted monthly income (heuristic): %s", self.state.borrower.monthly_income)

        # 5. Extract Loan Purpose
        if not self.state.borrower.loan_purpose and self.state.stage == ConversationStage.COLLECT_PURPOSE:
            purpose_candidate = re.sub(
                r'^(i want it for|it is for|for|purpose is|chahiye|ke liye)\s+',
                '',
                text_clean,
                flags=re.IGNORECASE
            ).strip()
            if len(purpose_candidate) > 2:
                self.state.borrower.loan_purpose = purpose_candidate.title()
                logger.info("Extracted loan purpose (heuristic): %s", self.state.borrower.loan_purpose)

    def _advance_stage_if_needed(self) -> None:
        # Advance through stages based on what's collected
        if self.state.stage == ConversationStage.COLLECT_NAME and self.state.borrower.name:
            self.state.stage = ConversationStage.COLLECT_LOAN_AMT
        elif self.state.stage == ConversationStage.COLLECT_LOAN_AMT and self.state.borrower.loan_amount:
            self.state.stage = ConversationStage.COLLECT_INCOME
        elif self.state.stage == ConversationStage.COLLECT_INCOME and self.state.borrower.monthly_income:
            self.state.stage = ConversationStage.COLLECT_PURPOSE
        elif self.state.stage == ConversationStage.COLLECT_PURPOSE and self.state.borrower.loan_purpose:
            self.state.stage = ConversationStage.CONFIRMATION

        if self.state.borrower.is_complete() and self.state.stage not in [
            ConversationStage.CONFIRMATION,
            ConversationStage.COMPLETED
        ]:
            self.state.stage = ConversationStage.CONFIRMATION
            logger.info("All fields collected — moving to confirmation stage")

    async def finalize_profile(self) -> BorrowerProfile:
        """
        Runs full LLM extraction on conversation history, merges with realtime data,
        marks call complete, and persists records to storage.
        """
        logger.info("Finalizing conversation profile for call_sid: %s", self.state.call_sid)

        # 1. Run LLM structured extraction pass
        try:
            extracted_dict = await self._extractor.extract_profile(
                history=self.state.history,
                current_profile=self.state.borrower.to_dict()
            )
            self.state.borrower.update_from_dict(extracted_dict)
        except Exception as e:
            logger.error("LLM extraction step encountered error, using current profile: %s", e)

        # 2. Mark call state complete
        self.state.complete_call()
        if self.state.borrower.is_complete():
            self.state.stage = ConversationStage.COMPLETED

        # 3. Persist to database & storage — each save gets its own error
        # handling so a failure in one doesn't prevent the others from being
        # attempted (e.g. a borrower-profile save failure shouldn't also
        # silently skip saving the transcript).
        try:
            await self._storage.save_call(self.state.to_call_dict())
        except Exception as e:
            logger.error("Failed to persist call metadata | call_sid: %s | error: %s", self.state.call_sid, e)

        try:
            await self._storage.save_borrower_profile(self.state.call_sid, self.state.borrower.to_dict())
        except Exception as e:
            logger.error("Failed to persist borrower profile | call_sid: %s | error: %s", self.state.call_sid, e)

        try:
            await self._storage.save_transcript(self.state.call_sid, self.state.history)
        except Exception as e:
            logger.error("Failed to persist transcript | call_sid: %s | error: %s", self.state.call_sid, e)

        logger.info("Persistence pass complete for call_sid: %s", self.state.call_sid)

        return self.state.borrower