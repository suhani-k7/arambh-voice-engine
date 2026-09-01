import asyncio
import os
import sys
from pathlib import Path

# Set up paths
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from factories.storage_factory import get_storage_handler
from factories.extractor_factory import get_extractor_handler
from core.conversation_state import ConversationState, BorrowerProfile


async def test_storage_direct():
    print("\n--- Testing Storage Handler Directly ---")
    storage = get_storage_handler()
    await storage.initialize()

    call_sid = "TEST_CALL_SID_999"
    test_call = {
        "call_sid": call_sid,
        "stream_sid": "TEST_STREAM_999",
        "stage": "completed",
        "turn_count": 6,
        "status": "completed",
        "started_at": "2026-09-01T20:00:00Z",
        "ended_at": "2026-09-01T20:02:15Z",
        "duration_seconds": 135.0
    }
    await storage.save_call(test_call)

    test_profile = {
        "name": "Rajesh Kumar",
        "phone": "9811223344",
        "loan_amount": "15,00,000",
        "monthly_income": "1,20,000",
        "loan_purpose": "Home Renovation",
        "is_complete": True
    }
    await storage.save_borrower_profile(call_sid, test_profile)

    test_history = [
        {"role": "assistant", "content": "Hello, may I have your name?", "timestamp": "2026-09-01T20:00:05Z"},
        {"role": "user", "content": "Mera naam Rajesh Kumar hai", "timestamp": "2026-09-01T20:00:15Z"},
        {"role": "assistant", "content": "Loan amount?", "timestamp": "2026-09-01T20:00:20Z"},
        {"role": "user", "content": "15 lakh rupaye chahiye", "timestamp": "2026-09-01T20:00:30Z"}
    ]
    await storage.save_transcript(call_sid, test_history)

    # Assert retrieval
    borrower = await storage.get_borrower_profile(call_sid)
    assert borrower is not None, "Borrower should not be None"
    assert borrower["name"] == "Rajesh Kumar", f"Expected Rajesh Kumar, got {borrower['name']}"
    assert borrower["loan_amount"] == "15,00,000", f"Expected 15,00,000, got {borrower['loan_amount']}"
    assert borrower["is_complete"] == 1, "Expected complete=1"

    transcript = await storage.get_call_transcript(call_sid)
    assert len(transcript) == 4, f"Expected 4 transcript items, got {len(transcript)}"

    all_borrowers = await storage.get_all_borrowers()
    assert any(b["call_sid"] == call_sid for b in all_borrowers), "Test call should be in all_borrowers list"

    print("✅ Storage Handler Direct Test Passed!")


async def test_extractor_direct():
    print("\n--- Testing LLM Extractor Directly ---")
    extractor = get_extractor_handler()

    sample_history = [
        {"role": "assistant", "content": "Hello! I'm Arambh. May I know your full name please?"},
        {"role": "user", "content": "Haan namaste, mera naam Sunita Rao hai and phone number is 9823012345"},
        {"role": "assistant", "content": "Great to meet you Sunita ji! What loan amount are you looking for?"},
        {"role": "user", "content": "Mujhe kareeb 8 lakh ka loan chahiye"},
        {"role": "assistant", "content": "Understood. May I know your monthly income?"},
        {"role": "user", "content": "Around 65 thousand per month"},
        {"role": "assistant", "content": "And what is the purpose of this loan?"},
        {"role": "user", "content": "Beti ki higher education ke liye admission fees deni hai"},
        {"role": "assistant", "content": "Thank you Sunita ji, I have noted that you need 8 Lakhs for education."}
    ]

    partial_profile = {"name": "", "phone": "", "loan_amount": "", "monthly_income": "", "loan_purpose": ""}

    extracted = await extractor.extract_profile(sample_history, partial_profile)
    print(f"Extracted Profile: {extracted}")

    assert "Sunita" in extracted.get("name", ""), f"Name extraction failed: {extracted.get('name')}"
    assert "8" in extracted.get("loan_amount", ""), f"Loan amount extraction failed: {extracted.get('loan_amount')}"
    assert "65" in extracted.get("monthly_income", ""), f"Monthly income extraction failed: {extracted.get('monthly_income')}"
    assert "education" in extracted.get("loan_purpose", "").lower(), f"Purpose extraction failed: {extracted.get('loan_purpose')}"
    assert extracted.get("is_complete") is True, "Expected is_complete=True"

    print("✅ LLM Extractor Direct Test Passed!")


async def main():
    await test_storage_direct()
    await test_extractor_direct()
    print("\n🎉 All Direct Tests Passed Successfully!")


if __name__ == "__main__":
    asyncio.run(main())
