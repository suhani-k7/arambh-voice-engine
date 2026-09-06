"""Phase 6 Step 6/7 - failure-mode characterization, now updated for fixes.

Step 6 forced each infrastructure adapter to raise or hang and documented
what actually happened (some fine, some real gaps). Step 7 closed the LLM-
hang, TTS-hang, and cascading-persistence-failure gaps found there; the
tests below were updated in place to assert the new, fixed behavior. The
STT-dropout and TTS-raise tests are unchanged since those two were already
handled acceptably and weren't in Step 7's scope.
"""
import asyncio
import base64
import json
from typing import Any, Callable, Coroutine

import pytest

import application.conversation_engine as conversation_engine
import infrastructure.telephony.twilio_handler as twilio_handler
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


# --- LLM timeout (fixed in Step 7) -----------------------------------------

@pytest.mark.asyncio
async def test_llm_timeout_falls_back_to_repeat_reply_instead_of_hanging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Step 7 fix: process_transcript() now wraps the LLM call in a timeout
    and falls back to a "could you repeat that" reply instead of stalling
    forever. Was: test_llm_hang_blocks_process_transcript_indefinitely,
    which asserted the opposite (a bare asyncio.TimeoutError bubbling out)."""
    monkeypatch.setattr(conversation_engine, "LLM_RESPONSE_TIMEOUT_SECONDS", 0.1)
    engine = ConversationEngine(
        llm=FakeLLMHandler(hang=True),
        call_sid="LLM_TIMEOUT_TEST",
        extractor=FakeExtractorHandler({}),
        storage=FakeStorageHandler(),
    )
    engine.get_greeting()
    response = await asyncio.wait_for(
        engine.process_transcript("My name is Test User", True), timeout=1.0
    )
    assert response == conversation_engine.LLM_TIMEOUT_FALLBACK_REPLY


@pytest.mark.asyncio
async def test_llm_timeout_produces_a_spoken_fallback_instead_of_silence(
    monkeypatch: pytest.MonkeyPatch, storage_calls: list[str],
) -> None:
    """Step 7 fix: a hanging LLM call on one turn no longer leaves the
    borrower with dead silence - process_transcript() times out and the
    fallback reply gets synthesized and played like any normal turn. Was:
    test_llm_hang_does_not_crash_media_stream_but_turn_is_silently_lost,
    which only asserted the WS handler didn't crash, not that a reply was
    ever produced."""
    monkeypatch.setattr(conversation_engine, "LLM_RESPONSE_TIMEOUT_SECONDS", 0.1)

    stt = FakeSTTHandler()
    llm = FakeLLMHandler(hang=True)
    tts = AlwaysOkTTSHandler()
    handler = TwilioHandler(stt_handler=stt, llm_handler=llm, tts_handler=tts)
    ws = FakeWebSocket()

    stream_task = asyncio.create_task(handler.handle_media_stream(ws))
    await asyncio.sleep(0)

    ws.push_inbound({
        "event": "start",
        "start": {"streamSid": "MZ_TEST", "callSid": "CA_LLM_TIMEOUT", "customParameters": {}},
    })
    await asyncio.sleep(0.05)

    assert stt.callback is not None
    # No longer needs to be a background task - it now returns (with the
    # fallback reply) well within a second instead of hanging forever.
    await stt.callback("My name is Test User", True)
    await asyncio.sleep(0.1)  # let the fallback reply get queued, synthesized, and played

    ws.push_inbound({"event": "stop", "stop": {}})
    await asyncio.wait_for(stream_task, timeout=1.0)

    media_frames = [f for f in ws.sent if f.get("event") == "media"]
    assert media_frames, "the fallback reply should have been synthesized and played"
    assert "save_borrower_profile" in storage_calls


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
async def test_tts_timeout_on_greeting_completes_instead_of_hanging_forever(
    monkeypatch: pytest.MonkeyPatch, storage_calls: list[str],
) -> None:
    """Step 7 fix: confirms the same TTS synthesis timeout also rescues a
    hung greeting rather than assuming it does, since the greeting's task
    takes a different path (bypasses response_queue entirely - see the
    queued-response test below). Was:
    test_tts_hang_on_greeting_leaks_the_task_but_does_not_block_finalization,
    which found the call finalized fine regardless, but only because the
    hung task was silently orphaned, not because anything rescued it. Now
    it actually completes - no orphaned task, no test-side cleanup needed."""
    monkeypatch.setattr(twilio_handler, "TTS_SYNTHESIS_TIMEOUT_SECONDS", 0.1)

    stt = FakeSTTHandler()
    llm = FakeLLMHandler(replies=[])
    tts = FailingTTSHandler(hang_from_call=1)  # hangs starting on the greeting itself
    handler = TwilioHandler(stt_handler=stt, llm_handler=llm, tts_handler=tts)
    ws = FakeWebSocket()

    stream_task = asyncio.create_task(handler.handle_media_stream(ws))
    await asyncio.sleep(0)
    ws.push_inbound({
        "event": "start",
        "start": {"streamSid": "MZ_TEST", "callSid": "CA_TTS_GREETING_TIMEOUT", "customParameters": {}},
    })
    await asyncio.sleep(0.3)  # let the 0.1s synthesis timeout fire and the greeting task finish

    ws.push_inbound({"event": "stop", "stop": {}})
    await asyncio.wait_for(stream_task, timeout=1.0)

    assert storage_calls == ["save_call", "save_borrower_profile", "save_transcript"]


@pytest.mark.asyncio
async def test_tts_timeout_on_queued_response_no_longer_blocks_finalization(
    monkeypatch: pytest.MonkeyPatch, storage_calls: list[str],
) -> None:
    """Step 7 fix for the serious gap: the TTS synthesis call inside speak()
    is now wrapped in a timeout, so a hung call on a queued turn no longer
    stalls response_worker (and thus finalize_profile) forever. Was:
    test_tts_hang_on_queued_response_blocks_call_finalization_indefinitely,
    which asserted the opposite and needed explicit task-cancellation
    cleanup at the end since nothing else would ever unstick it."""
    monkeypatch.setattr(twilio_handler, "TTS_SYNTHESIS_TIMEOUT_SECONDS", 0.1)

    stt = FakeSTTHandler()
    llm = FakeLLMHandler(replies=["Nice to meet you, Test User."])
    tts = FailingTTSHandler(hang_from_call=2)  # greeting (call 1) succeeds; the reply hangs
    handler = TwilioHandler(stt_handler=stt, llm_handler=llm, tts_handler=tts)
    ws = FakeWebSocket()

    stream_task = asyncio.create_task(handler.handle_media_stream(ws))
    await asyncio.sleep(0)
    ws.push_inbound({
        "event": "start",
        "start": {"streamSid": "MZ_TEST", "callSid": "CA_TTS_TIMEOUT", "customParameters": {}},
    })
    await asyncio.sleep(0.05)  # greeting synthesizes and plays fine

    assert stt.callback is not None
    await stt.callback("My name is Test User", True)
    await asyncio.sleep(0.3)  # let the 0.1s synthesis timeout fire on the queued reply

    ws.push_inbound({"event": "stop", "stop": {}})
    await asyncio.wait_for(stream_task, timeout=1.0)  # no longer hangs

    assert storage_calls == ["save_call", "save_borrower_profile", "save_transcript"]


# --- transcript / profile persistence failure (fixed in Step 7) -----------

@pytest.mark.asyncio
async def test_transcript_save_failure_does_not_prevent_the_other_saves() -> None:
    """Each save now has its own try/except. This scenario's outcome is
    unchanged from Step 6 (save_transcript is the last of the three calls,
    so its failure was never able to skip anything after it anyway) - kept
    to confirm the fix didn't regress the already-fine case. finalize_profile()
    still returns normally either way; that part of the gap (caller isn't
    told persistence failed) was explicitly out of scope for Step 7."""
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
async def test_borrower_profile_failure_no_longer_skips_the_transcript_save() -> None:
    """Step 7 fix for the sharper version of the gap: save_call,
    save_borrower_profile, and save_transcript now each get their own
    try/except in finalize_profile(), so a save_borrower_profile failure no
    longer prevents save_transcript from being attempted. Was:
    test_borrower_profile_failure_also_silently_skips_the_transcript_save,
    which asserted save_transcript was never even attempted."""
    storage = FakeStorageHandler(fail_methods=frozenset({"save_borrower_profile"}))
    engine = ConversationEngine(
        llm=FakeLLMHandler(replies=["Nice to meet you, Test User."]),
        call_sid="CASCADE_FIX_TEST",
        extractor=FakeExtractorHandler({"name": "Test User", "is_complete": False}),
        storage=storage,
    )
    engine.get_greeting()
    await engine.process_transcript("My name is Test User", True)

    profile = await engine.finalize_profile()  # must not raise

    assert profile.name == "Test User"
    assert storage.calls == ["save_call", "save_borrower_profile", "save_transcript"]
