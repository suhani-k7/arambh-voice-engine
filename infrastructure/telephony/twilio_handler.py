import json
from fastapi import WebSocket
from core.interfaces import TelephonyHandler
from utils.logger import AppLogger

logger = AppLogger.get_instance()

class TwilioHandler(TelephonyHandler):

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
                    logger.info("Stream started | streamSid: %s | callSid: %s", stream_sid, call_sid)

                elif event_type == "media":
                    payload = data["media"]["payload"]
                    chunk = data["media"]["chunk"]
                    logger.info("Audio chunk #%s received (%d bytes encoded)", chunk, len(payload))
                    # Phase 2: forward to Deepgram here

                elif event_type == "stop":
                    logger.info("Stream stopped by Twilio")
                    break

        except Exception as e:
            logger.error("Media stream error: %s", e)
        finally:
            logger.info("Media stream session ended")