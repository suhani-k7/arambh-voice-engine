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

class TTSHandler(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        """Convert text to mulaw 8kHz audio bytes ready for Twilio."""
        pass


class StorageHandler(ABC):
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize database tables and storage directories."""
        pass

    @abstractmethod
    async def save_call(self, call_data: dict) -> None:
        """Save or update call session metadata."""
        pass

    @abstractmethod
    async def save_borrower_profile(self, call_sid: str, profile_dict: dict) -> None:
        """Save extracted borrower profile for a call."""
        pass

    @abstractmethod
    async def save_transcript(self, call_sid: str, history: list[dict]) -> None:
        """Save conversation transcript turns."""
        pass

    @abstractmethod
    async def get_borrower_profile(self, call_sid: str) -> dict | None:
        """Retrieve borrower profile by call_sid."""
        pass

    @abstractmethod
    async def get_all_borrowers(self) -> list[dict]:
        """Retrieve all stored borrower profiles with call metadata."""
        pass

    @abstractmethod
    async def get_call_transcript(self, call_sid: str) -> list[dict]:
        """Retrieve conversation history for a call_sid."""
        pass


class ExtractorHandler(ABC):
    @abstractmethod
    async def extract_profile(self, history: list[dict], current_profile: dict) -> dict:
        """
        Analyze conversation history and return a structured dictionary of borrower profile fields.
        """
        pass
