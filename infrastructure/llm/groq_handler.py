from groq import AsyncGroq
from core.interfaces import LLMHandler
from config.settings import settings
from utils.logger import AppLogger

logger = AppLogger.get_instance()

SYSTEM_PROMPT = """You are Arambh, a warm and professional AI loan onboarding assistant for Arambh Finance.
You are conducting a voice call with a potential borrower in India.

Your job is to collect the following information through natural conversation:
1. Full name
2. Desired loan amount
3. Monthly income
4. Purpose of the loan

Guidelines:
- Be conversational, warm, and concise — this is a phone call, not a form
- Ask ONE question at a time
- Acknowledge what the borrower says before asking the next question
- If the borrower is unclear, politely ask for clarification
- Speak in simple English; you may mix in Hindi phrases naturally (like "ji", "bilkul", "theek hai")
- Keep responses short — under 3 sentences
- Once all information is collected, summarize it and confirm with the borrower
- Do not discuss loan approval, interest rates, or terms — only collect information

Current conversation stage is provided in each message for your context."""

class GroqHandler(LLMHandler):

    def __init__(self):
        self._client = AsyncGroq(api_key=settings.LLM_API_KEY)

    async def get_response(self, conversation_history: list[dict]) -> str:
        logger.info("Sending %d messages to Groq", len(conversation_history))
        try:
            response = await self._client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history,
                max_tokens=150,      # keep responses short for voice
                temperature=0.7,
            )
            reply = response.choices[0].message.content.strip()
            logger.info("Groq response: %s", reply)
            return reply
        except Exception as e:
            logger.error("Groq error: %s", e)
            return "I'm sorry, I didn't catch that. Could you please repeat?"