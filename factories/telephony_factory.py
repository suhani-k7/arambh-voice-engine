from core.interfaces import TelephonyHandler
from infrastructure.telephony.twilio_handler import TwilioHandler

def get_telephony_handler() -> TelephonyHandler:
    return TwilioHandler()