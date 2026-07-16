import httpx
import io
import wave
from core.interfaces import TTSHandler
from config.settings import settings
from utils.logger import AppLogger

logger = AppLogger.get_instance()

SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
try:
    import audioop
except ModuleNotFoundError:
    import audioop_lts as audioop
class SarvamHandler(TTSHandler):

    async def synthesize(self, text: str) -> bytes:
        """
        Calls Sarvam TTS, gets back WAV audio,
        converts it to mulaw 8kHz mono for Twilio.
        """
        logger.info("Synthesizing TTS for: %s", text[:80])

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                SARVAM_TTS_URL,
                headers={
                    "api-subscription-key": settings.SARVAM_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "inputs": [text],
                    "target_language_code": "en-IN",
                    "speaker": "meera",        # female Indian English voice
                    "speech_sample_rate": 8000, # match Twilio's sample rate
                    "enable_preprocessing": True,
                    "model": "bulbul:v1",
                }
            )

        if response.status_code != 200:
            logger.error("Sarvam TTS error %d: %s", response.status_code, response.text)
            raise RuntimeError(f"Sarvam TTS failed: {response.status_code}")

        data = response.json()

        # Sarvam returns base64-encoded WAV
        import base64
        wav_b64 = data["audios"][0]
        wav_bytes = base64.b64decode(wav_b64)

        # Convert WAV PCM → mulaw for Twilio
        mulaw_bytes = self._wav_to_mulaw(wav_bytes)
        logger.info("TTS synthesized: %d mulaw bytes", len(mulaw_bytes))
        return mulaw_bytes

    def _wav_to_mulaw(self, wav_bytes: bytes) -> bytes:
        """Convert WAV bytes to raw mulaw 8kHz mono bytes."""
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            pcm_data = wf.readframes(wf.getnframes())

        # Convert stereo to mono if needed
        if n_channels == 2:
            pcm_data = audioop.tomono(pcm_data, sampwidth, 0.5, 0.5)

        # Resample to 8kHz if needed
        if framerate != 8000:
            pcm_data, _ = audioop.ratecv(pcm_data, sampwidth, 1, framerate, 8000, None)

        # Convert PCM to mulaw
        mulaw_data = audioop.lin2ulaw(pcm_data, sampwidth)
        return mulaw_data