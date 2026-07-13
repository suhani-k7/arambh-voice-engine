from core.interfaces import STTHandler
from infrastructure.stt.deepgram_handler import DeepgramHandler

def get_stt_handler() -> STTHandler:
    return DeepgramHandler()