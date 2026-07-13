from core.conversation_state import ConversationState, ConversationStage, BorrowerProfile
from core.interfaces import LLMHandler
from utils.logger import AppLogger
import re

logger = AppLogger.get_instance()

class ConversationEngine:

    def __init__(self, llm: LLMHandler, call_sid: str):
        self._llm = llm
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

        # Build context message for LLM
        stage_context = f"[Current stage: {self.state.stage.value} | Missing fields: {self.state.borrower.missing_fields()}]"
        messages_with_context = self.state.history.copy()
        messages_with_context.insert(0, {"role": "user", "content": stage_context})

        response = await self._llm.get_response(self.state.history)
        self.state.add_assistant_message(response)
        self._advance_stage_if_needed()

        return response

    def get_greeting(self) -> str:
        greeting = "Hello! I'm Arambh, your loan onboarding assistant from Arambh Finance. I'd like to collect some basic information to get started. May I know your full name please?"
        self.state.add_assistant_message(greeting)
        self.state.advance_stage()
        return greeting

    def _extract_borrower_info(self, text: str) -> None:
        """Simple extraction — LLM handles nuance, this catches explicit patterns."""
        text_lower = text.lower()

        # Extract loan amount (e.g. "5 lakh", "500000", "5,00,000")
        if not self.state.borrower.loan_amount:
            amount_match = re.search(r'(\d[\d,]*)\s*(lakh|lac|thousand|k|crore)?', text_lower)
            if amount_match and self.state.stage.value in ["collect_loan_amount", "collect_income"]:
                self.state.borrower.loan_amount = amount_match.group(0).strip()
                logger.info("Extracted loan amount: %s", self.state.borrower.loan_amount)

        # Extract name (simple heuristic — first proper response after greeting)
        if not self.state.borrower.name and self.state.stage == ConversationStage.COLLECT_NAME:
            # Take the text as the name if it's short (1-4 words)
            words = text.strip().split()
            if 1 <= len(words) <= 4:
                self.state.borrower.name = text.strip().title()
                logger.info("Extracted name: %s", self.state.borrower.name)

    def _advance_stage_if_needed(self) -> None:
        if self.state.borrower.is_complete() and self.state.stage != ConversationStage.COMPLETED:
            self.state.stage = ConversationStage.CONFIRMATION
            logger.info("All fields collected — moving to confirmation")