import asyncio
import websockets
import json
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WEBSOCKET_URL = "ws://localhost:8000/ws/media-stream"

def fake_audio_payload() -> str:
    # 160 bytes of silence in mulaw encoding (what Twilio actually sends)
    return base64.b64encode(bytes([0xFF] * 160)).decode("utf-8")

async def simulate():
    print("Connecting to WebSocket...")
    async with websockets.connect(WEBSOCKET_URL) as ws:
        print("Connected!")

        # 1. Twilio sends 'connected' first
        await ws.send(json.dumps({
            "event": "connected",
            "protocol": "Call",
            "version": "1.0.0"
        }))
        print("Sent: connected")
        await asyncio.sleep(0.1)

        # 2. Then 'start'
        await ws.send(json.dumps({
            "event": "start",
            "sequenceNumber": "1",
            "start": {
                "streamSid": "MZ_FAKE_STREAM_SID_001",
                "callSid": "CA_FAKE_CALL_SID_001",
                "accountSid": "AC_FAKE_ACCOUNT_SID",
                "tracks": ["inbound"],
                "mediaFormat": {
                    "encoding": "audio/x-mulaw",
                    "sampleRate": 8000,
                    "channels": 1
                }
            },
            "streamSid": "MZ_FAKE_STREAM_SID_001"
        }))
        print("Sent: start")
        await asyncio.sleep(0.1)

        # 3. Send 10 fake audio chunks
        for i in range(1, 11):
            await ws.send(json.dumps({
                "event": "media",
                "sequenceNumber": str(i + 1),
                "media": {
                    "track": "inbound",
                    "chunk": str(i),
                    "timestamp": str(i * 20),
                    "payload": fake_audio_payload()
                },
                "streamSid": "MZ_FAKE_STREAM_SID_001"
            }))
            print(f"Sent: audio chunk #{i}")
            await asyncio.sleep(0.02)  # 20ms apart, like real Twilio

        # 4. Send 'stop'
        await ws.send(json.dumps({
            "event": "stop",
            "sequenceNumber": "12",
            "stop": {
                "accountSid": "AC_FAKE_ACCOUNT_SID",
                "callSid": "CA_FAKE_CALL_SID_001"
            },
            "streamSid": "MZ_FAKE_STREAM_SID_001"
        }))
        print("Sent: stop")
        await asyncio.sleep(0.2)
        print("\n✅ Simulation complete!")

asyncio.run(simulate())