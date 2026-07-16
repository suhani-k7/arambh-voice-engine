import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response

from config.settings import settings
from application.call_workflow import incoming_call_workflow, media_stream_workflow
from application.conversation_engine import ConversationEngine
from factories.llm_factory import get_llm_handler
from utils.logger import AppLogger

logger = AppLogger.get_instance()
app = FastAPI(title="Arambh Voice Engine")

# DEV ONLY — remove before Phase 7 deployment
_dev_engine = ConversationEngine(llm=get_llm_handler(), call_sid="DEV_TEST")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "Arambh Voice Engine"}


@app.post("/incoming-call")
async def incoming_call(request: Request):
    host = request.headers.get("host", "")
    twiml = await incoming_call_workflow(host)
    return Response(content=twiml, media_type="application/xml")


@app.websocket("/ws/media-stream")
async def media_stream(websocket: WebSocket):
    await media_stream_workflow(websocket)


# DEV ONLY — remove before Phase 7 deployment
@app.get("/dev/greeting")
async def dev_greeting():
    return {"response": _dev_engine.get_greeting()}


@app.post("/dev/inject-transcript")
async def dev_inject(payload: dict):
    text = payload.get("text", "")
    is_final = payload.get("is_final", True)
    response = await _dev_engine.process_transcript(text, is_final)
    return {
        "response": response,
        "stage": _dev_engine.state.stage.value,
        "borrower": _dev_engine.state.borrower.to_dict()
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)

async def main():
    print("Choose test mode:")
    print("1 — Audio stream (Phase 1 & 2)")
    print("2 — Conversation (Phase 3)")
    print("3 — TTS only (Phase 4)")
    print("4 — All")
    choice = input("Enter choice: ").strip()

    if choice == "1":
        await simulate_audio_stream()
    elif choice == "2":
        await simulate_conversation()
    elif choice == "3":
        await simulate_tts()
    elif choice == "4":
        await simulate_audio_stream()
        await simulate_conversation()
        await simulate_tts()
    else:
        print("Invalid choice")