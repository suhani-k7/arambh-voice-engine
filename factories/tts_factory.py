from core.interfaces import TTSHandler
from infrastructure.tts.sarvam_handler import SarvamHandler

def get_tts_handler() -> TTSHandler:
    return SarvamHandler()