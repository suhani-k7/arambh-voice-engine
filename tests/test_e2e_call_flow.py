"""Phase 6 Step 1 — E2E happy-path test for the full call pipeline.

Drives one complete borrower onboarding call through the /dev/* endpoints
(the same pattern tests/simulate_twilio.py uses interactively) and verifies
the resulting profile is persisted and retrievable via the REST API.

Requires a live dev server (`python main.py`) with real provider credentials
configured, since /dev/inject-transcript and /dev/complete-call exercise the
real LLMHandler and ExtractorHandler — see tests/conftest.py for the skip
behavior when the server isn't reachable.
"""
import httpx
import pytest

# A conversation scripted to supply every BorrowerProfile field in order,
# mirroring the working scenario in simulate_twilio.py's Phase 5 simulation.
HAPPY_PATH_TURNS: list[str] = [
    "My name is Priya Sharma",
    "I need a loan of 5 lakh rupees",
    "My monthly income is 80 thousand",
    "I want it for home renovation",
    "Yes, all the information is correct, please proceed",
]


@pytest.mark.asyncio
async def test_happy_path_full_call_flow(
    http_client: httpx.AsyncClient, dev_call_session: str
) -> None:
    """A complete, well-formed conversation should end with a fully
    populated borrower profile persisted and readable via GET /borrowers/{call_sid}.
    """
    call_sid = dev_call_session

    greeting_response = await http_client.get("/dev/greeting")
    greeting_response.raise_for_status()
    assert greeting_response.json()["response"]

    last_turn_data: dict = {}
    for turn in HAPPY_PATH_TURNS:
        turn_response = await http_client.post(
            "/dev/inject-transcript", json={"text": turn, "is_final": True}
        )
        turn_response.raise_for_status()
        last_turn_data = turn_response.json()
        assert last_turn_data["response"]

    assert last_turn_data["borrower"]["name"]
    assert last_turn_data["borrower"]["loan_amount"]
    assert last_turn_data["borrower"]["monthly_income"]
    assert last_turn_data["borrower"]["loan_purpose"]

    complete_response = await http_client.post("/dev/complete-call")
    complete_response.raise_for_status()
    completion_data = complete_response.json()

    assert completion_data["status"] == "persisted"
    assert completion_data["call_sid"] == call_sid
    final_profile = completion_data["final_profile"]
    assert final_profile["is_complete"] is True

    borrower_response = await http_client.get(f"/borrowers/{call_sid}")
    borrower_response.raise_for_status()
    persisted_profile = borrower_response.json()

    assert persisted_profile["name"] == final_profile["name"]
    assert persisted_profile["phone"] == final_profile["phone"]
    assert persisted_profile["loan_amount"] == final_profile["loan_amount"]
    assert persisted_profile["monthly_income"] == final_profile["monthly_income"]
    assert persisted_profile["loan_purpose"] == final_profile["loan_purpose"]
