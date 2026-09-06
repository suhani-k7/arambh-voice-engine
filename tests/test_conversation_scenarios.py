"""Phase 6 Step 2 - deterministic ConversationEngine scenario tests.

Unlike test_e2e_call_flow.py (Step 1's real-Groq smoke test), these never
call a live LLM: GroqHandler.get_response and LLMExtractorHandler
.extract_profile are monkeypatched with scripted per-scenario responses, so
what's under test is ConversationEngine's own logic (stage progression,
which BorrowerProfile fields the regex heuristic populates vs leaves null)
rather than the AI's output quality. Runs in-process via conftest's
asgi_client, since monkeypatch can't reach the separate `python main.py`
process that Step 1's tests target.
"""
import json
from pathlib import Path
from typing import Any, Callable, Coroutine

import httpx
import pytest

from infrastructure.extractor.llm_extractor import LLMExtractorHandler
from infrastructure.llm.groq_handler import GroqHandler

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "conversation_scenarios"
SCENARIO_FILES = sorted(FIXTURES_DIR.glob("*.json"))


def load_scenario(path: Path) -> dict[str, Any]:
    """Read one canned-conversation scenario fixture from disk."""
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def make_fake_llm_replies(
    replies: list[str],
) -> Callable[[GroqHandler, list[dict]], Coroutine[Any, Any, str]]:
    """Build a fake GroqHandler.get_response returning scripted replies in order."""
    queue = list(replies)

    async def fake_get_response(self: GroqHandler, conversation_history: list[dict]) -> str:
        return queue.pop(0)

    return fake_get_response


def make_fake_extractor(
    result: dict[str, Any],
) -> Callable[[LLMExtractorHandler, list[dict], dict], Coroutine[Any, Any, dict]]:
    """Build a fake LLMExtractorHandler.extract_profile returning a fixed result."""

    async def fake_extract_profile(
        self: LLMExtractorHandler, history: list[dict], current_profile: dict
    ) -> dict:
        return result

    return fake_extract_profile


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario_path", SCENARIO_FILES, ids=lambda p: p.stem)
async def test_conversation_scenario(
    scenario_path: Path,
    asgi_client: httpx.AsyncClient,
    asgi_dev_call_session: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive one scripted conversation and check stage/field progression + final persistence."""
    scenario = load_scenario(scenario_path)
    call_sid = asgi_dev_call_session

    monkeypatch.setattr(
        GroqHandler,
        "get_response",
        make_fake_llm_replies([turn["llm_reply"] for turn in scenario["turns"]]),
    )
    monkeypatch.setattr(
        LLMExtractorHandler,
        "extract_profile",
        make_fake_extractor(scenario["final_extraction_mock"]),
    )

    greeting_response = await asgi_client.get("/dev/greeting")
    greeting_response.raise_for_status()

    for turn in scenario["turns"]:
        turn_response = await asgi_client.post(
            "/dev/inject-transcript", json={"text": turn["user_text"], "is_final": True}
        )
        turn_response.raise_for_status()
        data = turn_response.json()
        assert data["stage"] == turn["expected_stage"]
        assert data["borrower"] == turn["expected_borrower"]

    complete_response = await asgi_client.post("/dev/complete-call")
    complete_response.raise_for_status()
    completion_data = complete_response.json()

    assert completion_data["final_profile"] == scenario["expected_final_profile"]
    assert completion_data["call_metadata"]["status"] == scenario["expected_final_status"]
    assert completion_data["call_metadata"]["stage"] == scenario["expected_final_stage"]

    borrower_response = await asgi_client.get(f"/borrowers/{call_sid}")
    borrower_response.raise_for_status()
    persisted = borrower_response.json()
    expected_final_profile = scenario["expected_final_profile"]
    for field in ["name", "phone", "loan_amount", "monthly_income", "loan_purpose"]:
        assert persisted[field] == expected_final_profile[field]
    assert bool(persisted["is_complete"]) == expected_final_profile["is_complete"]
