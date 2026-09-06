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


@pytest.fixture(scope="session")
def _ensure_server_running() -> None:
    """Skip tests that need it if the dev server isn't reachable.

    Not autouse: only tests that actually talk to a separately-running
    `python main.py` process (via http_client) need this. Tests that go
    through asgi_client (in-process ASGI transport) or drive handlers
    directly with fakes don't touch the live server at all and shouldn't
    be skipped because of it.
    """
    try:
        response = httpx.get(f"{BASE_URL}/health", timeout=2.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        pytest.skip(
            f"Dev server not reachable at {BASE_URL} (start it with "
            f"`python main.py` before running E2E tests): {exc}"
        )


@pytest_asyncio.fixture
async def http_client(_ensure_server_running: None) -> AsyncIterator[httpx.AsyncClient]:
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


@pytest_asyncio.fixture
async def asgi_client() -> AsyncIterator[httpx.AsyncClient]:
    """In-process client for tests that monkeypatch infrastructure adapters.

    `http_client` above talks over the network to a separately-running
    `python main.py` process, so monkeypatch in the test process can never
    reach into it. This fixture imports the FastAPI app directly and talks
    to it via an ASGI transport in the same process, so patching e.g.
    GroqHandler.get_response actually takes effect.
    """
    import main as main_module

    app = main_module.app
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


@pytest_asyncio.fixture
async def asgi_dev_call_session(asgi_client: httpx.AsyncClient) -> AsyncIterator[str]:
    """Same reset-to-a-fresh-call_sid contract as dev_call_session, but over asgi_client."""
    call_sid = make_call_sid("E2E_SCENARIO")
    response = await asgi_client.post("/dev/reset", json={"call_sid": call_sid})
    response.raise_for_status()
    yield call_sid
