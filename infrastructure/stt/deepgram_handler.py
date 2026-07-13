import base64
from typing import Callable, Awaitable
from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
from core.interfaces import STTHandler
from config.settings import settings
from utils.logger import AppLogger

logger = AppLogger.get_instance()

class DeepgramHandler(STTHandler):

    def __init__(self):
        self._client = DeepgramClient(api_key=settings.DEEPGRAM_API_KEY)
        self._connection = None
        self._transcript_callback: Callable[[str, bool], Awaitable[None]] | None = None

    def on_transcript(self, callback: Callable[[str, bool], Awaitable[None]]) -> None:
        self._transcript_callback = callback

    async def connect(self) -> None:
        logger.info("Connecting to Deepgram...")
        self._connection = self._client.listen.asyncwebsocket.v("1")

        async def on_message(self_inner, result, **kwargs):
            try:
                sentence = result.channel.alternatives[0].transcript
                is_final = result.is_final
                if sentence.strip():
                    logger.info("Transcript [final=%s]: %s", is_final, sentence)
                    if self._transcript_callback:
                        await self._transcript_callback(sentence, is_final)
            except Exception as e:
                logger.error("Transcript parsing error: %s", e)

        async def on_error(self_inner, error, **kwargs):
            logger.error("Deepgram error: %s", error)

        async def on_open(self_inner, open_event, **kwargs):
            logger.info("Deepgram connection opened")

        async def on_close(self_inner, **kwargs):
            logger.info("Deepgram connection closed")

        self._connection.on(LiveTranscriptionEvents.Transcript, on_message)
        self._connection.on(LiveTranscriptionEvents.Error, on_error)
        self._connection.on(LiveTranscriptionEvents.Open, on_open)
        self._connection.on(LiveTranscriptionEvents.Close, on_close)

        options = LiveOptions(
            model="nova-2",
            language="en-IN",       # Indian English
            encoding="mulaw",       # Twilio sends mulaw
            sample_rate=8000,       # Twilio sends 8kHz
            channels=1,
            punctuate=True,
            interim_results=True,   # get partial transcripts too
            endpointing=300,        # ms of silence = end of utterance
        )

        connected = await self._connection.start(options)
        if not connected:
            raise RuntimeError("Failed to connect to Deepgram")
        logger.info("Deepgram live session started")

    async def send_audio(self, audio_bytes: bytes) -> None:
        if self._connection:
            await self._connection.send(audio_bytes)

    async def disconnect(self) -> None:
        if self._connection:
            await self._connection.finish()
            logger.info("Deepgram session ended")