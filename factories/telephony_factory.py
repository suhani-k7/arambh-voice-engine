from core.interfaces import TelephonyHandler
from infrastructure.telephony.twilio_handler import TwilioHandler
from factories.stt_factory import get_stt_handler
from factories.llm_factory import get_llm_handler
from factories.tts_factory import get_tts_handler

def get_telephony_handler() -> TelephonyHandler:
    stt = get_stt_handler()
    llm = get_llm_handler()
    tts = get_tts_handler()
    return TwilioHandler(stt_handler=stt, llm_handler=llm, tts_handler=tts)