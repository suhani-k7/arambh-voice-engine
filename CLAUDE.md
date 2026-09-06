# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Arambh Voice Engine: an AI voice agent that automates initial borrower onboarding for home loans / loans-against-property (LAP). It runs real-time phone calls (Twilio media streams → Deepgram STT → Groq LLM → Sarvam TTS), holds a structured onboarding conversation, and persists an extracted borrower profile + transcript to SQLite. See `README.md` for the phase-by-phase roadmap (phases 0-5 done; 6-9 planned: E2E testing, deployment, analytics, docs).

## Commands

There is no test runner, linter, or build step configured (no pytest/Makefile/pyproject.toml) — everything is run as plain Python scripts against a live dev server.

```bash
# activate the venv first
source venv/bin/activate

# run the server (reads config/.env via config/settings.py)
python main.py                      # or: uvicorn main:app --reload --host 0.0.0.0 --port 8000

# interactive manual test menu (audio stream / conversation / TTS / persistence, or "5" for all)
python tests/simulate_twilio.py     # requires the server already running on localhost:8000

# direct unit-style checks for storage + LLM extraction (no server needed)
python tests/test_phase5_direct.py
```

Required env vars (`.env`, gitignored — see `config/settings.py`): `DEEPGRAM_API_KEY`, `SARVAM_API_KEY`, `LLM_API_KEY` are validated at startup and raise if missing. Also used: `LLM_MODEL`, `LLM_INFRA_ENDPOINT` (defaults to Groq), `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `HOST`, `PORT`.

For a real inbound call, `/incoming-call` needs to be reachable from Twilio (e.g. via an ngrok tunnel pointed at the local server); the public domain is currently taken directly from the request's `Host` header rather than a fixed config value (see Known gotchas below).

## Architecture

Clean-architecture / ports-and-adapters layering, four layers top to bottom:

- **`core/`** — framework-free domain layer. `interfaces.py` defines the abstract ports (`TelephonyHandler`, `STTHandler`, `LLMHandler`, `TTSHandler`, `StorageHandler`, `ExtractorHandler`). `conversation_state.py` holds `ConversationState`/`BorrowerProfile`/`ConversationStage` — the state machine for a single call.
- **`application/`** — orchestration, depends only on `core` interfaces, never on concrete providers directly:
  - `conversation_engine.py` — `ConversationEngine` is the central state machine. Each final STT transcript goes through `process_transcript()`: append to history → cheap regex-based `_extract_borrower_info()` for the *current* stage (fast, avoids waiting on an LLM round-trip mid-call) → build LLM message list with a stage/missing-fields context hint appended to the latest user turn → call the LLM → advance stage. At call end, `finalize_profile()` runs a second, more careful LLM extraction pass (`ExtractorHandler`) over the *full* transcript to reconcile/upgrade the realtime regex guesses, then persists via `StorageHandler`.
  - `audio_bridge.py` — `AudioBridge` paces synthesized mulaw audio to Twilio in real-time 20ms/160-byte chunks and implements barge-in (an interim, non-final STT transcript while the agent is speaking sets a stop event that aborts playback mid-stream).
  - `call_workflow.py` — thin wrapper used by `main.py` route handlers.
- **`infrastructure/`** — one concrete adapter per port, each depending only on its own third-party SDK + `config.settings`: `telephony/twilio_handler.py`, `stt/deepgram_handler.py`, `llm/groq_handler.py`, `tts/sarvam_handler.py`, `storage/sqlite_handler.py`, `extractor/llm_extractor.py`. (`infrastructure/llm/llama.py` is an empty placeholder, not wired up.)
- **`factories/`** — one function per port (`get_llm_handler()`, `get_stt_handler()`, etc.) that picks the concrete adapter. This is the single place to swap a provider (e.g. add a second `LLMHandler` and change `llm_factory.py`); nothing else in the codebase should import an `infrastructure/*` class directly. `storage_factory.py` and `extractor_factory.py` memoize a singleton instance; the others construct fresh per call.

Call lifecycle: Twilio hits `POST /incoming-call` → TwiML response opens a `<Connect><Stream>` to `/ws/media-stream` → `TwilioHandler.handle_media_stream` wires up a fresh `ConversationEngine` + `AudioBridge` for that WebSocket, streams inbound audio to Deepgram, feeds finalized transcripts through the engine, queues LLM responses onto a single-consumer `asyncio.Queue` (`response_worker`) so TTS playback stays strictly sequential, and on `stop`/disconnect calls `engine.finalize_profile()` to run the extraction pass and persist.

Persistence: SQLite (`storage/arambh.db`, WAL mode) with three tables — `calls`, `borrowers`, `transcripts` (all keyed by `call_sid`, upsert-on-conflict) — plus a parallel JSON transcript export per call under `storage/transcripts/<call_sid>.json`. Read paths are exposed via `GET /borrowers`, `GET /borrowers/{call_sid}`, `GET /calls/{call_sid}/transcript`.

`main.py` also exposes `/dev/*` endpoints (`greeting`, `inject-transcript`, `complete-call`, `reset`) against a module-level `_dev_engine`, used to drive `ConversationEngine` without a real phone call for manual testing (see `tests/simulate_twilio.py`). These are explicitly marked `# DEV ONLY — remove before Phase 7 deployment`.

## Known gotchas for upcoming phases

- No Twilio webhook signature validation exists yet (`TWILIO_AUTH_TOKEN` is loaded but unused for verification) — needed before Phase 7 deployment.
- The public callback domain for TwiML is read straight from the inbound request's `Host` header (`main.py` → `incoming_call_workflow`), which only works safely behind a trusted single-purpose tunnel (e.g. ngrok in dev); a real deployment should pin this to a configured value instead.
- `ConversationEngine`'s realtime regex extraction (`_extract_borrower_info`) is heuristic and stage-gated — it's a latency optimization, not the source of truth; the LLM pass in `finalize_profile()` is what actually reconciles the final stored profile.
