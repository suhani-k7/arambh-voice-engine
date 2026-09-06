"""Shared pytest fixtures for E2E tests that drive the /dev/* endpoints
against an already-running instance of the FastAPI app (same pattern as
tests/simulate_twilio.py). No test manages the server's lifecycle here;
start it yourself first with `python main.py`.
"""
import time
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio

BASE_URL = "http://localhost:8000"


@pytest.fixture(scope="session", autouse=True)
def _ensure_server_running() -> None:
    """Skip the whole E2E session if the dev server isn't reachable."""
    try:
        response = httpx.get(f"{BASE_URL}/health", timeout=2.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        pytest.skip(
            f"Dev server not reachable at {BASE_URL} (start it with "
            f"`python main.py` before running E2E tests): {exc}"
        )


@pytest_asyncio.fixture
async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Async HTTP client scoped to a single test, pointed at the dev server."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        yield client


def make_call_sid(prefix: str = "E2E_TEST") -> str:
    """Generate a unique call_sid so parallel/sequential test runs don't collide."""
    return f"{prefix}_{int(time.time() * 1000)}"


@pytest_asyncio.fixture
async def dev_call_session(http_client: httpx.AsyncClient) -> AsyncIterator[str]:
    """Reset the module-level dev ConversationEngine to a fresh call_sid.

    The /dev/* endpoints in main.py share a single global engine instance,
    so every test that drives a call through them must reset it first to
    avoid bleeding state from a previous test.
    """
    call_sid = make_call_sid()
    response = await http_client.post("/dev/reset", json={"call_sid": call_sid})
    response.raise_for_status()
    yield call_sid
