import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

class Settings:
    def __init__(self):
        self.DEEPGRAM_API_KEY: str = os.getenv("DEEPGRAM_API_KEY", "").strip()
        self.SARVAM_API_KEY: str = os.getenv("SARVAM_API_KEY", "").strip()
        self.LLM_API_KEY: str = os.getenv("LLM_API_KEY", "").strip()
        self.LLM_MODEL: str = os.getenv("LLM_MODEL", "openai/gpt-oss-120b").strip()
        self.LLM_INFRA_ENDPOINT: str = os.getenv(
            "LLM_INFRA_ENDPOINT", "https://api.groq.com/openai/v1/chat/completions"
        ).strip()
        self.TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        self.TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        self.HOST: str = os.getenv("HOST", "0.0.0.0")
        self.PORT: int = int(os.getenv("PORT", 8000))
        self._assert_valid_environment()


    def _assert_valid_environment(self) -> None:
        missing = []
        if not self.DEEPGRAM_API_KEY: missing.append("DEEPGRAM_API_KEY")
        if not self.SARVAM_API_KEY: missing.append("SARVAM_API_KEY")
        if not self.LLM_API_KEY: missing.append("LLM_API_KEY")
        if missing:
            raise ValueError(f"❌ MISSING ENVIRONMENT KEYS: {', '.join(missing)}")

settings = Settings()