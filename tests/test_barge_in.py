"""Phase 6 Step 5 - barge-in test.

Barge-in lives entirely inside TwilioHandler.handle_media_stream (the
is_speaking flag, the in-flight speak task, the AudioBridge it creates).
The /dev/* endpoints drive ConversationEngine directly and never touch
TwilioHandler/AudioBridge/TTS at all, so they structurally cannot reach
this code path - this test instead drives TwilioHandler directly with
fake STT/LLM/TTS handlers and a fake WebSocket.
"""
import asyncio
import json
from typing import Any, Callable, Coroutine

import pytest

from core.interfaces import LLMHandler, STTHandler, TTSHandler
from infrastructure.telephony.twilio_handler import TwilioHandler

TranscriptCallback = Callable[[str, bool], Coroutine[Any, Any, None]]


class FakeWebSocket:
    """Stand-in for FastAPI's WebSocket: a queue of inbound frames the test
    feeds, and a list capturing every outbound frame "sent to Twilio"."""

    def __init__(self) -> None:
        self._inbound: asyncio.Queue[str] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []

    def push_inbound(self, message: dict[str, Any]) -> None:
        self._inbound.put_nowait(json.dumps(message))

    async def receive_text(self) -> str:
        return await self._inbound.get()

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))


class FakeSTTHandler(STTHandler):
    """Captures the registered on_transcript callback so the test can fire
    transcripts on demand, instead of needing a real Deepgram connection."""

    def __init__(self) -> None:
        self.callback: TranscriptCallback | None = None

    def on_transcript(self, callback: TranscriptCallback) -> None:
        self.callback = callback

    async def connect(self) -> None:
        pass

    async def send_audio(self, audio_bytes: bytes) -> None:
        pass

    async def disconnect(self) -> None:
        pass


class FakeLLMHandler(LLMHandler):
    """Returns scripted replies in order, one per call, instead of hitting Groq."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)

    async def get_response(self, conversation_history: list[dict]) -> str:
        return self._replies.pop(0)


class FakeTTSHandler(TTSHandler):
    """The `block_on_call`-th synthesize() call blocks until released or
    cancelled, standing in for "playback artificially held open"; every
    other call returns immediately. Defaults to blocking call 2 (the
    greeting is always call 1, so this holds open the first real turn)."""

    def __init__(self, block_on_call: int = 2) -> None:
        self._block_on_call = block_on_call
        self.release_blocked_call = asyncio.Event()
        self.blocked_call_cancelled = False
        self.call_count = 0

    async def synthesize(self, text: str) -> bytes:
        self.call_count += 1
        if self.call_count == self._block_on_call:
            try:
                await self.release_blocked_call.wait()
            except asyncio.CancelledError:
                self.blocked_call_cancelled = True
                raise
        return bytes([0xFF] * 320)


@pytest.mark.asyncio
async def test_final_transcript_during_speech_triggers_barge_in() -> None:
    """A final transcript arriving while the agent is speaking must clear
    Twilio's buffered audio, cancel the in-flight TTS task, and let the new
    utterance be processed immediately rather than waiting for it to finish.
    """
    stt = FakeSTTHandler()
    llm = FakeLLMHandler(["Reply to turn one.", "Reply to turn two."])
    tts = FakeTTSHandler()
    handler = TwilioHandler(stt_handler=stt, llm_handler=llm, tts_handler=tts)
    ws = FakeWebSocket()

    stream_task = asyncio.create_task(handler.handle_media_stream(ws))
    await asyncio.sleep(0)  # let handle_media_stream register the STT callback

    ws.push_inbound({
        "event": "start",
        "start": {"streamSid": "MZ_TEST", "callSid": "CA_TEST", "customParameters": {}},
    })
    await asyncio.sleep(0.05)  # let the greeting's speak task (synthesize call 1) finish

    assert tts.call_count == 1, "greeting should have synthesized and completed"

    assert stt.callback is not None
    await stt.callback("My name is Priya Sharma", True)  # turn 1: final transcript
    await asyncio.sleep(0.05)  # let speak() start synthesizing turn 1 (call 2) and block

    assert tts.call_count == 2, "turn 1's synthesis should be in flight and blocked"

    await stt.callback("Actually, forget that", True)  # turn 2: barge-in mid-speech
    await asyncio.sleep(0.05)

    assert tts.blocked_call_cancelled is True
    assert any(frame.get("event") == "clear" for frame in ws.sent), (
        "barge-in must send Twilio a clear event to flush buffered audio"
    )

    await asyncio.sleep(0.05)
    assert tts.call_count == 3, "turn 2's synthesis should have started right away"

    ws.push_inbound({"event": "stop", "stop": {}})
    await asyncio.wait_for(stream_task, timeout=2.0)
