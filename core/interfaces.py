from abc import ABC, abstractmethod
from fastapi import WebSocket
from typing import Callable, Awaitable

class TelephonyHandler(ABC):

    @abstractmethod
    async def handle_incoming_call(self, host: str) -> str:
        pass

    @abstractmethod
    async def handle_media_stream(self, websocket: WebSocket) -> None:
        pass


class STTHandler(ABC):

    @abstractmethod
    async def connect(self) -> None:
        """Open connection to STT provider."""
        pass

    @abstractmethod
    async def send_audio(self, audio_bytes: bytes) -> None:
        """Send raw audio bytes to STT provider."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close STT connection."""
        pass

    @abstractmethod
    def on_transcript(self, callback: Callable[[str, bool], Awaitable[None]]) -> None:
        """
        Register a callback for transcripts.
        callback(text, is_final) where is_final=True means sentence is complete.
        """
        pass

class LLMHandler(ABC):
    @abstractmethod
    async def get_response(self, conversation_history: list[dict]) -> str:
        """Given full conversation history, return agent's next response."""
        pass