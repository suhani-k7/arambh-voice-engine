import asyncio
import base64
import json
from fastapi import WebSocket
from core.interfaces import TelephonyHandler, STTHandler, LLMHandler, TTSHandler
from application.conversation_engine import ConversationEngine
from application.audio_bridge import AudioBridge
from utils.latency import elapsed_since_ms, mark, record_duration, timed_stage
from utils.logger import AppLogger

logger = AppLogger.get_instance()


class TwilioHandler(TelephonyHandler):

    def __init__(self, stt_handler: STTHandler, llm_handler: LLMHandler, tts_handler: TTSHandler):
        self._stt = stt_handler
        self._llm = llm_handler
        self._tts = tts_handler

    async def handle_incoming_call(self, host: str) -> str:
        logger.info("Incoming call received")
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>Please wait while we connect you to our AI assistant.</Say>
    <Connect>
        <Stream url="wss://{host}/ws/media-stream" />
    </Connect>
</Response>"""
        return twiml

    async def handle_media_stream(self, websocket: WebSocket) -> None:
        logger.info("Media stream WebSocket opened")

        engine = ConversationEngine(llm=self._llm, call_sid="UNKNOWN")
        bridge: AudioBridge | None = None
        response_queue: asyncio.Queue = asyncio.Queue()

        # Per-call speaking state, used to detect and cancel barge-in targets.
        # `is_speaking` covers TTS synthesis *and* playback (a superset of
        # AudioBridge.is_playing, which only covers playback), since a final
        # transcript arriving mid-synthesis should also interrupt.
        is_speaking = False
        current_speak_task: asyncio.Task | None = None

        async def speak(text: str) -> None:
            """Synthesize and stream TTS audio."""
            nonlocal is_speaking
            is_speaking = True
            try:
                call_sid = engine.state.call_sid
                gap_ms = elapsed_since_ms(call_sid, "stt_final_transcript")
                if gap_ms is not None:
                    record_duration(call_sid, "stt_final_to_tts_start", gap_ms)
                async with timed_stage(call_sid, "tts_synthesis"):
                    mulaw_bytes = await self._tts.synthesize(text)
                if bridge:
                    await bridge.play(mulaw_bytes)
            except asyncio.CancelledError:
                logger.info("Speak task cancelled by barge-in | call_sid: %s", engine.state.call_sid)
                raise
            except Exception as e:
                logger.error("TTS/playback error: %s", e)
            finally:
                is_speaking = False

        async def response_worker() -> None:
            """Processes agent responses sequentially from the queue."""
            nonlocal current_speak_task
            while True:
                text = await response_queue.get()
                if text is None:
                    break
                current_speak_task = asyncio.create_task(speak(text))
                try:
                    await current_speak_task
                except asyncio.CancelledError:
                    pass  # barge-in cancelled this turn's audio; move on to the next queued response
                finally:
                    current_speak_task = None
                response_queue.task_done()

        async def on_transcript(text: str, is_final: bool) -> None:
            if not is_final:
                # Interim transcript — trigger barge-in if agent is speaking
                if bridge and bridge.is_playing:
                    bridge.barge_in()
                return

            if is_speaking:
                logger.info("Barge-in: final transcript arrived while agent is speaking | call_sid: %s", engine.state.call_sid)
                if bridge:
                    await bridge.send_clear()
                if current_speak_task and not current_speak_task.done():
                    current_speak_task.cancel()

            mark(engine.state.call_sid, "stt_final_transcript")
            response = await engine.process_transcript(text, is_final)
            if response:
                await response_queue.put(response)

        self._stt.on_transcript(on_transcript)
        await self._stt.connect()

        # Start response worker
        worker_task = asyncio.create_task(response_worker())

        try:
            while True:
                message = await websocket.receive_text()
                data = json.loads(message)
                event_type = data.get("event")

                if event_type == "connected":
                    logger.info("Twilio stream connected")

                elif event_type == "start":
                    stream_sid = data["start"]["streamSid"]
                    call_sid = data["start"]["callSid"]
                    engine.state.call_sid = call_sid
                    engine.state.stream_sid = stream_sid
                    
                    # Capture caller phone from Twilio custom parameters if present
                    custom_params = data["start"].get("customParameters", {})
                    caller_phone = custom_params.get("From") or custom_params.get("Caller")
                    if caller_phone and not engine.state.borrower.phone:
                        engine.state.borrower.phone = str(caller_phone)

                    bridge = AudioBridge(websocket, stream_sid)
                    logger.info("Stream started | streamSid: %s | callSid: %s", stream_sid, call_sid)

                    # Speak greeting (tracked the same way as queued responses,
                    # so barge-in during the greeting itself can cancel it too)
                    greeting = engine.get_greeting()
                    current_speak_task = asyncio.create_task(speak(greeting))

                elif event_type == "media":
                    payload = data["media"]["payload"]
                    audio_bytes = base64.b64decode(payload)
                    await self._stt.send_audio(audio_bytes)

                elif event_type == "stop":
                    logger.info("Stream stopped by Twilio")
                    break

        except Exception as e:
            logger.error("Media stream error: %s", e)
        finally:
            await response_queue.put(None)  # stop worker
            await worker_task
            await self._stt.disconnect()
            
            # Finalize extraction and persist to SQLite + JSON
            try:
                final_profile = await engine.finalize_profile()
                logger.info("Finalized and persisted borrower profile: %s", final_profile.to_dict())
            except Exception as fe:
                logger.error("Error during call finalization and persistence: %s", fe)

            logger.info("Media stream session ended")