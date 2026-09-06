import asyncio
import websockets
import json
import base64
import math
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


def percentile(data: list[float], pct: float) -> float:
    """Nearest-rank percentile of `data` for pct in [0, 100]; 0.0 if data is empty."""
    if not data:
        return 0.0
    ordered = sorted(data)
    rank = max(0, min(len(ordered) - 1, math.ceil(pct / 100 * len(ordered)) - 1))
    return ordered[rank]


PROFILING_TURNS: list[str] = [
    "My name is Priya Sharma",
    "I need a loan of 5 lakh rupees",
    "My monthly income is 80 thousand",
    "I want it for home renovation",
    "Yes, all the information is correct, please proceed",
]


async def simulate_latency_profiling(n_calls: int = 10) -> None:
    """Phase 6 Step 4 — runs n_calls full calls through the /dev/* endpoints
    and reports p50/p95 latency per pipeline stage, using Step 3's
    utils/latency.py instrumentation (read back via /dev/last-call-metrics).

    /dev/* drives ConversationEngine directly and never touches STT or TTS,
    so only the "llm_response" stage will have samples here — profiling
    stt_final_to_tts_start / tts_synthesis requires a real call through
    /ws/media-stream, which this script's audio simulation doesn't wire up
    to the LLM/TTS pipeline.
    """
    print(f"\n--- Latency Profiling: {n_calls} calls through /dev/* endpoints ---")
    stage_samples: dict[str, list[float]] = {}

    async with httpx.AsyncClient(timeout=30.0) as client:
        for i in range(1, n_calls + 1):
            call_sid = f"PROFILE_CALL_{i}_{int(asyncio.get_event_loop().time() * 1000)}"
            await client.post(f"{BASE_URL}/dev/reset", json={"call_sid": call_sid})
            await client.get(f"{BASE_URL}/dev/greeting")

            for turn in PROFILING_TURNS:
                await client.post(
                    f"{BASE_URL}/dev/inject-transcript", json={"text": turn, "is_final": True}
                )

            await client.post(f"{BASE_URL}/dev/complete-call")

            metrics_response = await client.get(f"{BASE_URL}/dev/last-call-metrics")
            for entry in metrics_response.json().get("metrics", []):
                stage_samples.setdefault(entry["stage"], []).append(entry["duration_ms"])

            print(f"Call {i}/{n_calls} done ({call_sid})")

    print("\n--- Latency Report (ms) ---")
    if not stage_samples:
        print("No latency samples recorded.")
        return

    print(f"{'stage':<24}{'count':>7}{'p50':>10}{'p95':>10}{'min':>10}{'max':>10}")
    for stage, samples in stage_samples.items():
        print(
            f"{stage:<24}{len(samples):>7}"
            f"{percentile(samples, 50):>10.1f}"
            f"{percentile(samples, 95):>10.1f}"
            f"{min(samples):>10.1f}"
            f"{max(samples):>10.1f}"
        )

    print(
        "\nNote: /dev/* endpoints only exercise ConversationEngine directly, so "
        "only 'llm_response' has samples here. STT/TTS stages "
        "(stt_final_to_tts_start, tts_synthesis) require a real call through "
        "/ws/media-stream."
    )


async def main():
    print("Choose test mode:")
    print("1 — Audio stream (Phase 1 & 2)")
    print("2 — Conversation (Phase 3)")
    print("3 — TTS only (Phase 4)")
    print("4 — Persistence & Structured Extraction (Phase 5)")
    print("5 — Run All Tests")
    print("6 — Latency Profiling (Phase 6)")
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
    elif choice == "6":
        n_calls_input = input("How many calls to profile? [10]: ").strip()
        n_calls = int(n_calls_input) if n_calls_input else 10
        await simulate_latency_profiling(n_calls)
    else:
        print("Invalid choice")

if __name__ == "__main__":
    asyncio.run(main())