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


async def simulate_persistence_and_extraction():
    """Phase 5 test — tests full conversation, LLM extraction pass, SQLite storage, and transcript export."""
    print("\n--- Phase 5: Persistence & Structured Extraction Simulation ---")
    async with httpx.AsyncClient(timeout=30.0) as client:
        call_sid = f"SIM_CALL_{int(asyncio.get_event_loop().time() * 1000)}"

        # 1. Reset dev engine for a clean session
        r = await client.post(f"{BASE_URL}/dev/reset", json={"call_sid": call_sid})
        print(f"🔄 Initialized call session: {r.json()}")

        # 2. Get greeting
        r = await client.get(f"{BASE_URL}/dev/greeting")
        print(f"\nAgent: {r.json()['response']}")

        # 3. Simulate realistic Indian Hinglish conversation turns
        turns = [
            "Namaste, mera naam Amit Patel hai and my phone is 9876543210",
            "Mujhe 12 lakh rupaye ka loan chahiye",
            "Meri monthly income approx 95 thousand per month hai",
            "Ye loan mujhe new dairy machinery business expand karne ke liye chahiye",
            "Haan sab information theek hai, please proceed kar dijiye",
        ]

        for turn in turns:
            print(f"\nBorrower: {turn}")
            r = await client.post(
                f"{BASE_URL}/dev/inject-transcript",
                json={"text": turn, "is_final": True}
            )
            data = r.json()
            print(f"Agent: {data['response']}")
            print(f"Stage: {data['stage']} | Real-time Profile: {data['borrower']}")
            await asyncio.sleep(0.5)

        # 4. Trigger Call Completion & LLM Extraction
        print("\n⏳ Completing call & running LLM extraction pass...")
        r = await client.post(f"{BASE_URL}/dev/complete-call")
        completion_data = r.json()
        print(f"✅ Call completion response:\n{json.dumps(completion_data, indent=2)}")

        # 5. Query Persistence API
        print(f"\n🔍 Querying GET /borrowers/{call_sid}...")
        r = await client.get(f"{BASE_URL}/borrowers/{call_sid}")
        saved_borrower = r.json()
        print(f"Stored Profile in Database:\n{json.dumps(saved_borrower, indent=2)}")

        print(f"\n🔍 Querying GET /calls/{call_sid}/transcript...")
        r = await client.get(f"{BASE_URL}/calls/{call_sid}/transcript")
        saved_transcript = r.json()
        print(f"Stored Transcript Count: {saved_transcript.get('turns_count')}")

        # Check transcript JSON export file
        transcript_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "storage", "transcripts", f"{call_sid}.json"
        )
        if os.path.exists(transcript_file):
            print(f"✅ Transcript JSON file verified at: {transcript_file}")
        else:
            print(f"⚠️ Transcript JSON file not found at: {transcript_file}")

        print("\n🎉 Phase 5 Persistence & Extraction Simulation Complete!")


async def main():
    print("Choose test mode:")
    print("1 — Audio stream (Phase 1 & 2)")
    print("2 — Conversation (Phase 3)")
    print("3 — TTS only (Phase 4)")
    print("4 — Persistence & Structured Extraction (Phase 5)")
    print("5 — Run All Tests")
    choice = input("Enter choice: ").strip()

    if choice == "1":
        await simulate_audio_stream()
    elif choice == "2":
        await simulate_conversation()
    elif choice == "3":
        await simulate_tts()
    elif choice == "4":
        await simulate_persistence_and_extraction()
    elif choice == "5":
        await simulate_audio_stream()
        await simulate_tts()
        await simulate_conversation()
        await simulate_persistence_and_extraction()
    else:
        print("Invalid choice")

if __name__ == "__main__":
    asyncio.run(main())