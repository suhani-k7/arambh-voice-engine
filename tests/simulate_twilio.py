import asyncio
import websockets
import json
import base64
import os
import sys
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WEBSOCKET_URL = "ws://localhost:8000/ws/media-stream"
BASE_URL = "http://localhost:8000"


def load_audio_payload() -> list[str]:
    chunk = bytes([0x7F] * 160)
    return [base64.b64encode(chunk).decode("utf-8")] * 50

async def simulate_tts():
    """Phase 4 test — directly calls TTS and saves output to a WAV-like file."""
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from infrastructure.tts.sarvam_handler import SarvamHandler

    print("\n--- TTS Simulation ---")
    handler = SarvamHandler()
    test_text = "Namaste Priya ji, thank you for sharing that with me. What loan amount are you looking for?"
    print(f"Synthesizing: '{test_text}'")

    mulaw_bytes = await handler.synthesize(test_text)
    print(f"✅ Got {len(mulaw_bytes)} mulaw bytes from Sarvam")

    # Save as raw mulaw file (you can play it with ffplay or audacity)
    out_path = "tests/tts_output.ul"
    with open(out_path, "wb") as f:
        f.write(mulaw_bytes)
    print(f"Saved to {out_path} — play with: ffplay -f mulaw -ar 8000 -ac 1 {out_path}")


async def simulate_audio_stream():
    """Phase 1 & 2 test — sends fake audio over WebSocket."""
    print("\n--- Audio Stream Simulation ---")
    async with websockets.connect(WEBSOCKET_URL) as ws:
        print("Connected!")
        await ws.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
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
        await asyncio.sleep(1)
        print("✅ Audio stream simulation complete!")


async def simulate_conversation():
    """Phase 3 test — simulates a full borrower conversation via dev endpoints."""
    print("\n--- Conversation Simulation ---")
    async with httpx.AsyncClient() as client:

        # Get greeting
        r = await client.get(f"{BASE_URL}/dev/greeting")
        print(f"\nAgent: {r.json()['response']}")

        # Simulate borrower turns
        turns = [
            "My name is Priya Sharma",
            "I need a loan of 5 lakh rupees",
            "My monthly income is 80 thousand",
            "I want it for home renovation",
        ]

        for turn in turns:
            print(f"\nBorrower: {turn}")
            r = await client.post(
                f"{BASE_URL}/dev/inject-transcript",
                json={"text": turn, "is_final": True}
            )
            data = r.json()
            print(f"Agent: {data['response']}")
            print(f"Stage: {data['stage']} | Profile: {data['borrower']}")
            await asyncio.sleep(0.5)

    print("\n✅ Conversation simulation complete!")


async def main():
    print("Choose test mode:")
    print("1 — Audio stream (Phase 1 & 2)")
    print("2 — Conversation (Phase 3)")
    print("3 — Both")
    choice = input("Enter choice: ").strip()

    if choice == "1":
        await simulate_audio_stream()
    elif choice == "2":
        await simulate_conversation()
    elif choice == "3":
        await simulate_audio_stream()
        await simulate_conversation()
    else:
        print("Invalid choice")

asyncio.run(main())