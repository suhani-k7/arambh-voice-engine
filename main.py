import time
import uvicorn
from fastapi import FastAPI, Request, WebSocket, Body
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


from factories.storage_factory import get_storage_handler

storage = get_storage_handler()

@app.on_event("startup")
async def on_startup():
    await storage.initialize()
    logger.info("Arambh Voice Engine initialized")


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


# --- PERSISTENCE & DATA APIS ---

@app.get("/borrowers")
async def list_borrowers():
    """Retrieve all stored borrower profiles and call metadata."""
    borrowers = await storage.get_all_borrowers()
    return {
        "count": len(borrowers),
        "borrowers": borrowers
    }


@app.get("/borrowers/{call_sid}")
async def get_borrower(call_sid: str):
    """Retrieve a specific borrower profile by call_sid."""
    profile = await storage.get_borrower_profile(call_sid)
    if not profile:
        return Response(content='{"error": "Borrower not found"}', status_code=404, media_type="application/json")
    return profile


@app.get("/calls/{call_sid}/transcript")
async def get_transcript(call_sid: str):
    """Retrieve the full turn-by-turn conversation transcript for a call."""
    transcript = await storage.get_call_transcript(call_sid)
    return {
        "call_sid": call_sid,
        "turns_count": len(transcript),
        "transcript": transcript
    }


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


@app.post("/dev/complete-call")
async def dev_complete_call():
    """Manually trigger call completion, LLM extraction pass, and database persistence."""
    profile = await _dev_engine.finalize_profile()
    return {
        "status": "persisted",
        "call_sid": _dev_engine.state.call_sid,
        "final_profile": profile.to_dict(),
        "call_metadata": _dev_engine.state.to_call_dict()
    }


@app.post("/dev/reset")
async def dev_reset(payload: dict = Body(default={})):
    """Reset the dev conversation engine state."""
    global _dev_engine
    call_sid = (payload or {}).get("call_sid", f"DEV_TEST_{int(time.time())}")
    _dev_engine = ConversationEngine(llm=get_llm_handler(), call_sid=call_sid)
    return {"status": "reset", "call_sid": call_sid}


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)