"""Phase 6 Step 6 - characterizing current failure-mode behavior.

These tests document what actually happens today when an infrastructure
adapter misbehaves - they do not fix anything (that's Step 7). Adapters
are forced to raise or hang via fakes/monkeypatch; no production code is
touched in this step.
"""
import asyncio
import base64
import contextlib
import json
from typing import Any, Callable, Coroutine

import pytest

from application.conversation_engine import ConversationEngine
from core.interfaces import ExtractorHandler, LLMHandler, STTHandler, StorageHandler, TTSHandler
from infrastructure.extractor.llm_extractor import LLMExtractorHandler
from infrastructure.storage.sqlite_handler import SQLiteStorageHandler
from infrastructure.telephony.twilio_handler import TwilioHandler

TranscriptCallback = Callable[[str, bool], Coroutine[Any, Any, None]]


# --- fakes ----------------------------------------------------------------

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
    """Captures the registered on_transcript callback for the test to fire on demand."""

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


class DroppingSTTHandler(FakeSTTHandler):
    """Simulates a dropped STT connection: forwarding audio starts raising."""

    async def send_audio(self, audio_bytes: bytes) -> None:
        raise ConnectionError("simulated Deepgram connection drop")


class FakeLLMHandler(LLMHandler):
    """Returns scripted replies, or raises/hangs on every call instead."""

    def __init__(
        self,
        replies: list[str] | None = None,
        raise_error: Exception | None = None,
        hang: bool = False,
    ) -> None:
        self._replies = list(replies) if replies else []
        self._raise_error = raise_error
        self._hang = hang

    async def get_response(self, conversation_history: list[dict]) -> str:
        if self._hang:
            await asyncio.Event().wait()
        if self._raise_error is not None:
            raise self._raise_error
        return self._replies.pop(0)


class AlwaysOkTTSHandler(TTSHandler):
    async def synthesize(self, text: str) -> bytes:
        return bytes([0xFF] * 160)


class FailingTTSHandler(TTSHandler):
    """Raises on every synthesize() call, or hangs from the `hang_from_call`-th
    call onward (1-indexed; 0 means never hang) so a test can let the greeting
    (always call 1) succeed and only hang a later, queued turn's synthesis."""

    def __init__(self, raise_error: Exception | None = None, hang_from_call: int = 0) -> None:
        self._raise_error = raise_error
        self._hang_from_call = hang_from_call
        self.call_count = 0

    async def synthesize(self, text: str) -> bytes:
        self.call_count += 1
        if self._hang_from_call and self.call_count >= self._hang_from_call:
            await asyncio.Event().wait()
        if self._raise_error is not None:
            raise self._raise_error
        return bytes([0xFF] * 160)


class FakeStorageHandler(StorageHandler):
    """Records every call made to it; can be configured to raise on specific methods."""

    def __init__(self, fail_methods: frozenset[str] = frozenset()) -> None:
        self._fail_methods = fail_methods
        self.calls: list[str] = []

    async def initialize(self) -> None:
        self.calls.append("initialize")

    async def save_call(self, call_data: dict) -> None:
        self.calls.append("save_call")
        if "save_call" in self._fail_methods:
            raise RuntimeError("simulated save_call failure")

    async def save_borrower_profile(self, call_sid: str, profile_dict: dict) -> None:
        self.calls.append("save_borrower_profile")
        if "save_borrower_profile" in self._fail_methods:
            raise RuntimeError("simulated save_borrower_profile failure")

    async def save_transcript(self, call_sid: str, history: list[dict]) -> None:
        self.calls.append("save_transcript")
        if "save_transcript" in self._fail_methods:
            raise RuntimeError("simulated save_transcript failure")

    async def get_borrower_profile(self, call_sid: str) -> dict | None:
        return None

    async def get_all_borrowers(self) -> list[dict]:
        return []

    async def get_call_transcript(self, call_sid: str) -> list[dict]:
        return []


class FakeExtractorHandler(ExtractorHandler):
    def __init__(self, result: dict) -> None:
        self._result = result

    async def extract_profile(self, history: list[dict], current_profile: dict) -> dict:
        return self._result


@pytest.fixture
def storage_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """TwilioHandler's ConversationEngine falls back to the real singleton
    LLMExtractorHandler/SQLiteStorageHandler when none are injected, so
    full-flow tests here monkeypatch those classes to stay offline/free."""
    calls: list[str] = []

    async def fake_extract_profile(self: LLMExtractorHandler, history: list[dict], current_profile: dict) -> dict:
        return current_profile

    async def fake_save_call(self: SQLiteStorageHandler, call_data: dict) -> None:
        calls.append("save_call")

    async def fake_save_borrower_profile(self: SQLiteStorageHandler, call_sid: str, profile_dict: dict) -> None:
        calls.append("save_borrower_profile")

    async def fake_save_transcript(self: SQLiteStorageHandler, call_sid: str, history: list[dict]) -> None:
        calls.append("save_transcript")

    monkeypatch.setattr(LLMExtractorHandler, "extract_profile", fake_extract_profile)
    monkeypatch.setattr(SQLiteStorageHandler, "save_call", fake_save_call)
    monkeypatch.setattr(SQLiteStorageHandler, "save_borrower_profile", fake_save_borrower_profile)
    monkeypatch.setattr(SQLiteStorageHandler, "save_transcript", fake_save_transcript)
    return calls


# --- LLM timeout ------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_hang_blocks_process_transcript_indefinitely() -> None:
    """Characterizes: ConversationEngine has no timeout around the LLM call,
    so a hanging LLMHandler stalls process_transcript() forever."""
    engine = ConversationEngine(
        llm=FakeLLMHandler(hang=True),
        call_sid="LLM_HANG_TEST",
        extractor=FakeExtractorHandler({}),
        storage=FakeStorageHandler(),
    )
    engine.get_greeting()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(engine.process_transcript("My name is Test User", True), timeout=0.3)


@pytest.mark.asyncio
async def test_llm_hang_does_not_crash_media_stream_but_turn_is_silently_lost(
    storage_calls: list[str],
) -> None:
    """Characterizes: a hanging LLM call on one turn doesn't crash or hang
    the whole WebSocket handler (it still shuts down cleanly on "stop"), but
    that turn's response is silently lost forever - no timeout, no fallback."""
    stt = FakeSTTHandler()
    llm = FakeLLMHandler(hang=True)
    tts = AlwaysOkTTSHandler()
    handler = TwilioHandler(stt_handler=stt, llm_handler=llm, tts_handler=tts)
    ws = FakeWebSocket()

    stream_task = asyncio.create_task(handler.handle_media_stream(ws))
    await asyncio.sleep(0)

    ws.push_inbound({
        "event": "start",
        "start": {"streamSid": "MZ_TEST", "callSid": "CA_LLM_HANG", "customParameters": {}},
    })
    await asyncio.sleep(0.05)

    assert stt.callback is not None
    # Deepgram would invoke this via its own internal task, independent of the WS loop
    asyncio.create_task(stt.callback("My name is Test User", True))
    await asyncio.sleep(0.05)

    ws.push_inbound({"event": "stop", "stop": {}})
    # The WS handler must not hang just because one turn's LLM call is stuck
    await asyncio.wait_for(stream_task, timeout=1.0)

    assert "save_borrower_profile" in storage_calls  # call still finalizes


# --- STT dropout --------------------------------------------------------

@pytest.mark.asyncio
async def test_stt_send_audio_failure_ends_call_but_persists_partial_profile(
    storage_calls: list[str],
) -> None:
    """Characterizes: forwarding audio to a dropped STT connection raises,
    and the WS receive loop has only one broad try/except around the whole
    loop, so the call ends immediately (no retry, no reconnect) rather than
    degrading gracefully - but the existing finally block still runs
    finalize_profile(), so whatever partial profile was gathered beforehand
    does get persisted."""
    stt = DroppingSTTHandler()
    llm = FakeLLMHandler(replies=["Nice to meet you, Test User."])
    tts = AlwaysOkTTSHandler()
    handler = TwilioHandler(stt_handler=stt, llm_handler=llm, tts_handler=tts)
    ws = FakeWebSocket()

    stream_task = asyncio.create_task(handler.handle_media_stream(ws))
    await asyncio.sleep(0)

    ws.push_inbound({
        "event": "start",
        "start": {"streamSid": "MZ_TEST", "callSid": "CA_STT_DROP", "customParameters": {}},
    })
    await asyncio.sleep(0.05)

    assert stt.callback is not None
    await stt.callback("My name is Test User", True)  # gather some info before the drop
    await asyncio.sleep(0.05)

    # Borrower's audio keeps arriving, but forwarding it to STT now fails
    ws.push_inbound({
        "event": "media",
        "media": {"payload": base64.b64encode(bytes([0xFF] * 4)).decode()},
    })

    await asyncio.wait_for(stream_task, timeout=1.0)  # must not hang

    assert storage_calls == ["save_call", "save_borrower_profile", "save_transcript"]


# --- TTS failure ----------------------------------------------------------

@pytest.mark.asyncio
async def test_tts_raise_recovers_gracefully_call_continues(storage_calls: list[str]) -> None:
    """Characterizes: speak()'s existing except Exception already catches a
    raised TTS failure and swallows it - the call does not crash or hang,
    but the borrower gets dead silence for that turn (no fallback audio)."""
    stt = FakeSTTHandler()
    llm = FakeLLMHandler(replies=["Nice to meet you, Test User."])
    tts = FailingTTSHandler(raise_error=RuntimeError("simulated Sarvam 500"))
    handler = TwilioHandler(stt_handler=stt, llm_handler=llm, tts_handler=tts)
    ws = FakeWebSocket()

    stream_task = asyncio.create_task(handler.handle_media_stream(ws))
    await asyncio.sleep(0)
    ws.push_inbound({
        "event": "start",
        "start": {"streamSid": "MZ_TEST", "callSid": "CA_TTS_RAISE", "customParameters": {}},
    })
    await asyncio.sleep(0.05)  # greeting's TTS raises and is swallowed

    assert stt.callback is not None
    await stt.callback("My name is Test User", True)
    await asyncio.sleep(0.05)  # turn 1's TTS also raises and is swallowed

    assert not any(frame.get("event") == "media" for frame in ws.sent), (
        "no audio should have reached Twilio since every synthesize() call failed"
    )

    ws.push_inbound({"event": "stop", "stop": {}})
    await asyncio.wait_for(stream_task, timeout=1.0)  # call still ends cleanly

    assert "save_borrower_profile" in storage_calls


@pytest.mark.asyncio
async def test_tts_hang_on_greeting_leaks_the_task_but_does_not_block_finalization(
    storage_calls: list[str],
) -> None:
    """Characterizes a surprise: the greeting's speak() task is a standalone
    asyncio.create_task(...), never routed through response_queue/
    response_worker at all - so even though it hangs forever, finally's
    `await worker_task` never waits on it. The call finalizes normally and
    the hung greeting task is simply leaked (silently, forever, until the
    process exits or a test runner cancels it during teardown)."""
    stt = FakeSTTHandler()
    llm = FakeLLMHandler(replies=[])
    tts = FailingTTSHandler(hang_from_call=1)  # hangs starting on the greeting itself
    handler = TwilioHandler(stt_handler=stt, llm_handler=llm, tts_handler=tts)
    ws = FakeWebSocket()

    stream_task = asyncio.create_task(handler.handle_media_stream(ws))
    await asyncio.sleep(0)
    ws.push_inbound({
        "event": "start",
        "start": {"streamSid": "MZ_TEST", "callSid": "CA_TTS_GREETING_HANG", "customParameters": {}},
    })
    await asyncio.sleep(0.05)  # greeting's TTS is now stuck hanging forever, unobserved

    ws.push_inbound({"event": "stop", "stop": {}})
    await asyncio.wait_for(stream_task, timeout=1.0)  # finalizes anyway - the hang is orphaned

    assert storage_calls == ["save_call", "save_borrower_profile", "save_transcript"]


@pytest.mark.asyncio
async def test_tts_hang_on_queued_response_blocks_call_finalization_indefinitely(
    storage_calls: list[str],
) -> None:
    """Characterizes the real gap: once a transcript produces a queued
    response, response_worker awaits that turn's speak() task directly, so a
    hang there stalls response_worker forever - and handle_media_stream's
    finally block (`await worker_task`) never completes even after Twilio
    sends "stop", so finalize_profile() never runs and nothing persists."""
    stt = FakeSTTHandler()
    llm = FakeLLMHandler(replies=["Nice to meet you, Test User."])
    tts = FailingTTSHandler(hang_from_call=2)  # greeting (call 1) succeeds; the reply hangs
    handler = TwilioHandler(stt_handler=stt, llm_handler=llm, tts_handler=tts)
    ws = FakeWebSocket()

    stream_task = asyncio.create_task(handler.handle_media_stream(ws))
    await asyncio.sleep(0)
    ws.push_inbound({
        "event": "start",
        "start": {"streamSid": "MZ_TEST", "callSid": "CA_TTS_HANG", "customParameters": {}},
    })
    await asyncio.sleep(0.05)  # greeting synthesizes and plays fine

    assert stt.callback is not None
    await stt.callback("My name is Test User", True)
    await asyncio.sleep(0.05)  # the reply is now queued and its synthesis is stuck

    ws.push_inbound({"event": "stop", "stop": {}})
    await asyncio.sleep(0.05)

    done, pending = await asyncio.wait({stream_task}, timeout=0.3)
    assert stream_task in pending, "handle_media_stream should still be stuck, not finished"
    assert storage_calls == [], "finalize_profile should never even have started"

    # Tear down the leaked chain explicitly: cancelling stream_task cascades
    # through its `await worker_task` -> `await current_speak_task` chain.
    stream_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await stream_task


# --- transcript / profile persistence failure -----------------------------

@pytest.mark.asyncio
async def test_transcript_persistence_failure_silently_drops_without_signaling_caller() -> None:
    """Characterizes a real gap: when save_transcript specifically fails, the
    call+profile ARE persisted (they ran first and succeeded), but the
    transcript itself is silently lost - and finalize_profile() returns
    normally either way, so nothing tells the caller persistence failed."""
    storage = FakeStorageHandler(fail_methods=frozenset({"save_transcript"}))
    engine = ConversationEngine(
        llm=FakeLLMHandler(replies=["Nice to meet you, Test User."]),
        call_sid="TRANSCRIPT_FAIL_TEST",
        extractor=FakeExtractorHandler({"name": "Test User", "is_complete": False}),
        storage=storage,
    )
    engine.get_greeting()
    await engine.process_transcript("My name is Test User", True)

    profile = await engine.finalize_profile()  # must not raise

    assert profile.name == "Test User"
    assert storage.calls == ["save_call", "save_borrower_profile", "save_transcript"]


@pytest.mark.asyncio
async def test_borrower_profile_failure_also_silently_skips_the_transcript_save() -> None:
    """Characterizes a sharper version of the same gap: all three saves share
    one try/except in finalize_profile(), so a failure on save_borrower_profile
    (which runs before save_transcript) means save_transcript never even gets
    attempted - losing the transcript too, even though nothing about the
    transcript itself was ever at fault."""
    storage = FakeStorageHandler(fail_methods=frozenset({"save_borrower_profile"}))
    engine = ConversationEngine(
        llm=FakeLLMHandler(replies=["Nice to meet you, Test User."]),
        call_sid="CASCADE_FAIL_TEST",
        extractor=FakeExtractorHandler({"name": "Test User", "is_complete": False}),
        storage=storage,
    )
    engine.get_greeting()
    await engine.process_transcript("My name is Test User", True)

    profile = await engine.finalize_profile()  # must not raise

    assert profile.name == "Test User"
    assert storage.calls == ["save_call", "save_borrower_profile"]
    assert "save_transcript" not in storage.calls
