import asyncio
import base64
import json
from utils.logger import AppLogger

logger = AppLogger.get_instance()

CHUNK_SIZE = 160  # 20ms of mulaw at 8kHz


class AudioBridge:
    """
    Breaks TTS audio into 160-byte chunks and sends them
    to Twilio over the media stream WebSocket.
    Also handles barge-in: stops playback if borrower speaks.
    """

    def __init__(self, websocket, stream_sid: str):
        self._ws = websocket
        self._stream_sid = stream_sid
        self._is_playing = False
        self._stop_event = asyncio.Event()

    async def play(self, mulaw_bytes: bytes) -> None:
        """Stream audio to Twilio in 20ms chunks."""
        self._is_playing = True
        self._stop_event.clear()
        total_chunks = len(mulaw_bytes) // CHUNK_SIZE

        logger.info("Playing %d audio chunks to Twilio", total_chunks)

        try:
            for i in range(0, len(mulaw_bytes), CHUNK_SIZE):
                if self._stop_event.is_set():
                    logger.info("Barge-in detected — stopping playback at chunk %d/%d", i // CHUNK_SIZE, total_chunks)
                    break

                chunk = mulaw_bytes[i:i + CHUNK_SIZE]
                # Pad last chunk if needed
                if len(chunk) < CHUNK_SIZE:
                    chunk = chunk + bytes(CHUNK_SIZE - len(chunk))

                payload = base64.b64encode(chunk).decode("utf-8")
                await self._ws.send_text(json.dumps({
                    "event": "media",
                    "streamSid": self._stream_sid,
                    "media": {"payload": payload}
                }))
                await asyncio.sleep(0.02)  # 20ms per chunk, real-time pace
        finally:
            # Must reset even on cancellation, or is_playing stays stuck True
            # and future interim-transcript barge-in checks would misfire.
            self._is_playing = False

        logger.info("Audio playback finished")

    async def send_clear(self) -> None:
        """Tell Twilio to immediately drop any audio it has buffered but not yet played.

        Stopping our own chunk-sending loop isn't enough — Twilio buffers audio
        slightly ahead of real-time, so without this a barge-in would still let
        a fragment of the old response play out on the call.
        """
        logger.info("Sending 'clear' event to Twilio media stream")
        await self._ws.send_text(json.dumps({
            "event": "clear",
            "streamSid": self._stream_sid,
        }))

    def barge_in(self) -> None:
        """Call this when borrower starts speaking to stop agent audio."""
        if self._is_playing:
            logger.info("Barge-in triggered")
            self._stop_event.set()

    @property
    def is_playing(self) -> bool:
        return self._is_playing