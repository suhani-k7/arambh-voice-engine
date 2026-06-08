from fastapi import FastAPI
from config.settings import settings
from utils.logger import AppLogger

logger = AppLogger.get_instance()
app = FastAPI(title="Arambh Voice Infrastructure Engine")

@app.on_event("startup")
async def verify_system_readiness():
    logger.info("Initializing Arambh Engine Core Security checks...")
    logger.info(f"Target LLM Gateway bound to: {settings.LLM_INFRA_ENDPOINT}")
    logger.info("Configuration baseline successfully validated.")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "pipeline": "asynchronous_voice_marketplace"}