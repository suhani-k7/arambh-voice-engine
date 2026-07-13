from core.interfaces import TelephonyHandler
from infrastructure.telephony.twilio_handler import TwilioHandler
from factories.stt_factory import get_stt_handler

def get_telephony_handler() -> TelephonyHandler:
    stt = get_stt_handler()
    return TwilioHandler(stt_handler=stt)