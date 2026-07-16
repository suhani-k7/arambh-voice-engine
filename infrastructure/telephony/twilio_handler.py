import asyncio
import base64
import json
from fastapi import WebSocket
from core.interfaces import TelephonyHandler, STTHandler, LLMHandler, TTSHandler
from application.conversation_engine import ConversationEngine
from application.audio_bridge import AudioBridge
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

        async def speak(text: str) -> None:
            """Synthesize and stream TTS audio."""
            try:
                mulaw_bytes = await self._tts.synthesize(text)
                if bridge:
                    await bridge.play(mulaw_bytes)
            except Exception as e:
                logger.error("TTS/playback error: %s", e)

        async def response_worker() -> None:
            """Processes agent responses sequentially from the queue."""
            while True:
                text = await response_queue.get()
                if text is None:
                    break
                await speak(text)
                response_queue.task_done()

        async def on_transcript(text: str, is_final: bool) -> None:
            if not is_final:
                # Interim transcript — trigger barge-in if agent is speaking
                if bridge and bridge.is_playing:
                    bridge.barge_in()
                return

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
                    bridge = AudioBridge(websocket, stream_sid)
                    logger.info("Stream started | streamSid: %s | callSid: %s", stream_sid, call_sid)

                    # Speak greeting
                    greeting = engine.get_greeting()
                    asyncio.create_task(speak(greeting))

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
            logger.info("Final borrower profile: %s", engine.state.borrower.to_dict())
            logger.info("Media stream session ended")