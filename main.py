import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response

from config.settings import settings
from application.call_workflow import incoming_call_workflow, media_stream_workflow
from utils.logger import AppLogger

logger = AppLogger.get_instance()
app = FastAPI(title="Arambh Voice Engine")

@app.get("/health")
async def health():
    return {"status": "ok", "service": "Arambh Voice Engine"}


@app.post("/incoming-call")
async def incoming_call(request: Request):
    # Extract ngrok host from the incoming request URL so you don't need it hardcoded
    host = request.headers.get("host", "")
    twiml = await incoming_call_workflow(host)
    return Response(content=twiml, media_type="application/xml")


@app.websocket("/ws/media-stream")
async def media_stream(websocket: WebSocket):
    await media_stream_workflow(websocket)


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)