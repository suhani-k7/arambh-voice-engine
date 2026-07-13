import base64
import json
from fastapi import WebSocket
from core.interfaces import TelephonyHandler, STTHandler, LLMHandler
from application.conversation_engine import ConversationEngine
from utils.logger import AppLogger

logger = AppLogger.get_instance()

class TwilioHandler(TelephonyHandler):

    def __init__(self, stt_handler: STTHandler, llm_handler: LLMHandler):
        self._stt = stt_handler
        self._llm = llm_handler

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

        async def on_transcript(text: str, is_final: bool):
            response = await engine.process_transcript(text, is_final)
            if response:
                logger.info(">>> AGENT RESPONSE: %s", response)
                # Phase 4: send response to TTS and back to Twilio here

        self._stt.on_transcript(on_transcript)
        await self._stt.connect()

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
                    logger.info("Stream started | streamSid: %s | callSid: %s", stream_sid, call_sid)
                    # Send greeting
                    greeting = engine.get_greeting()
                    logger.info(">>> GREETING: %s", greeting)
                    # Phase 4: speak greeting via TTS here

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
            await self._stt.disconnect()
            logger.info("Media stream session ended")
            logger.info("Final borrower profile: %s", engine.state.borrower.to_dict())