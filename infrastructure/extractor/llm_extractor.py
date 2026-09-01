import json
import re
from groq import AsyncGroq
from core.interfaces import ExtractorHandler
from config.settings import settings
from utils.logger import AppLogger

logger = AppLogger.get_instance()

EXTRACTION_SYSTEM_PROMPT = """You are an expert loan data extraction system for Arambh Finance (India).
Your job is to extract structured borrower information from a phone conversation transcript.

Extract the following fields accurately:
1. "name": Full name of the borrower in Title Case (e.g. "Priya Sharma"). Empty string "" if not mentioned.
2. "phone": 10-digit Indian phone number if mentioned. Empty string "" if not mentioned.
3. "loan_amount": Desired loan amount in clear standardized format (e.g. "5,00,000" or "10 Lakhs"). Empty string "" if not mentioned.
4. "monthly_income": Monthly income in clear standardized format (e.g. "80,000" or "1.5 Lakh"). Empty string "" if not mentioned.
5. "loan_purpose": Concise purpose of loan (e.g. "Home Renovation", "Education", "Business Expansion", "Medical Emergency"). Empty string "" if not mentioned.
6. "is_complete": true if name, loan_amount, monthly_income, AND loan_purpose are all present and non-empty; otherwise false.

CRITICAL RULES:
- Output ONLY valid JSON matching this exact structure:
{
  "name": "...",
  "phone": "...",
  "loan_amount": "...",
  "monthly_income": "...",
  "loan_purpose": "...",
  "is_complete": true/false
}
- Do not output markdown fences, code blocks, or explanatory text. Return ONLY the raw JSON object.
- Parse Hinglish and natural Indian English phrasing accurately (e.g. "paanch lakh" -> "5,00,000", "assi hazaar" -> "80,000", "ghar ka renovation" -> "Home Renovation").
"""


class LLMExtractorHandler(ExtractorHandler):

    def __init__(self):
        self._client = AsyncGroq(api_key=settings.LLM_API_KEY)

    async def extract_profile(self, history: list[dict], current_profile: dict) -> dict:
        """
        Takes conversation history and produces structured JSON profile.
        """
        if not history:
            logger.warning("Empty history provided to LLMExtractor")
            return current_profile

        # Format transcript lines
        transcript_text = "\n".join([
            f"{msg.get('role', 'unknown').capitalize()}: {msg.get('content', '')}"
            for msg in history
            if msg.get("content")
        ])

        user_content = f"--- TRANSCRIPT ---\n{transcript_text}\n\n--- CURRENT PARTIAL PROFILE ---\n{json.dumps(current_profile, indent=2)}\n\nPlease extract and return the final structured JSON borrower profile."

        logger.info("Running LLM extraction on transcript with %d messages", len(history))

        try:
            response = await self._client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.1,  # Low temperature for deterministic extraction
                max_tokens=1000,
                response_format={"type": "json_object"}
            )


            raw_content = response.choices[0].message.content.strip()
            logger.info("Raw LLM extraction response: %s", raw_content)

            extracted_data = json.loads(raw_content)

            # Clean and merge with existing profile
            result = current_profile.copy() if current_profile else {}
            for key in ["name", "phone", "loan_amount", "monthly_income", "loan_purpose"]:
                val = extracted_data.get(key)
                if val and str(val).strip():
                    result[key] = str(val).strip()

            # Check completion
            is_complete = bool(
                result.get("name") and
                result.get("loan_amount") and
                result.get("monthly_income") and
                result.get("loan_purpose")
            )
            result["is_complete"] = is_complete

            logger.info("Final extracted profile: %s", result)
            return result

        except Exception as e:
            logger.error("Error during LLM extraction: %s", e)
            # Fallback to current profile if extraction fails
            return current_profile
