from core.interfaces import ExtractorHandler
from infrastructure.extractor.llm_extractor import LLMExtractorHandler

_extractor_instance: ExtractorHandler | None = None

def get_extractor_handler() -> ExtractorHandler:
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = LLMExtractorHandler()
    return _extractor_instance
