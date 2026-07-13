from core.interfaces import LLMHandler
from infrastructure.llm.groq_handler import GroqHandler

def get_llm_handler() -> LLMHandler:
    return GroqHandler()