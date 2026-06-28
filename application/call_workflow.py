from fastapi import WebSocket
from factories.telephony_factory import get_telephony_handler
from utils.logger import AppLogger

logger = AppLogger.get_instance()
_handler = get_telephony_handler()

async def incoming_call_workflow(ngrok_domain: str) -> str:
    return await _handler.handle_incoming_call(ngrok_domain)

async def media_stream_workflow(websocket: WebSocket) -> None:
    await websocket.accept()
    await _handler.handle_media_stream(websocket)