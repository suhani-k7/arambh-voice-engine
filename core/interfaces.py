from abc import ABC, abstractmethod
from fastapi import WebSocket

class TelephonyHandler(ABC):

    @abstractmethod
    async def handle_incoming_call(self, host: str) -> str:
        """Returns TwiML XML string."""
        pass

    @abstractmethod
    async def handle_media_stream(self, websocket: WebSocket) -> None:
        """Handles live audio WebSocket from Twilio."""
        pass