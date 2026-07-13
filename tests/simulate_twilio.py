import asyncio
import websockets
import json
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WEBSOCKET_URL = "ws://localhost:8000/ws/media-stream"

def load_audio_payload() -> list[str]:
    """
    Generate simple mulaw-encoded silence chunks.
    For real transcription testing, replace this with actual mulaw audio bytes.
    Twilio sends 160 bytes per 20ms chunk at 8kHz mulaw.
    """
    # 0x7F is mulaw silence
    chunk = bytes([0x7F] * 160)
    return [base64.b64encode(chunk).decode("utf-8")] * 50  # 50 chunks = ~1 second


async def simulate():
    print("Connecting to WebSocket...")
    async with websockets.connect(WEBSOCKET_URL) as ws:
        print("Connected!")

        await ws.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        print("Sent: connected")
        await asyncio.sleep(0.1)

        await ws.send(json.dumps({
            "event": "start",
            "sequenceNumber": "1",
            "start": {
                "streamSid": "MZ_FAKE_STREAM_SID_001",
                "callSid": "CA_FAKE_CALL_SID_001",
                "accountSid": "AC_FAKE",
                "tracks": ["inbound"],
                "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1}
            },
            "streamSid": "MZ_FAKE_STREAM_SID_001"
        }))
        print("Sent: start")
        await asyncio.sleep(0.1)

        chunks = load_audio_payload()
        for i, payload in enumerate(chunks, 1):
            await ws.send(json.dumps({
                "event": "media",
                "sequenceNumber": str(i + 1),
                "media": {"track": "inbound", "chunk": str(i), "timestamp": str(i * 20), "payload": payload},
                "streamSid": "MZ_FAKE_STREAM_SID_001"
            }))
            await asyncio.sleep(0.02)
        print(f"Sent: {len(chunks)} audio chunks")

        await ws.send(json.dumps({
            "event": "stop",
            "sequenceNumber": str(len(chunks) + 2),
            "stop": {"accountSid": "AC_FAKE", "callSid": "CA_FAKE_CALL_SID_001"},
            "streamSid": "MZ_FAKE_STREAM_SID_001"
        }))
        print("Sent: stop")
        await asyncio.sleep(1)
        print("\n✅ Simulation complete!")

asyncio.run(simulate())