# Voice Engine

[![Tests](https://github.com/suhani-k7/arambh-voice-engine/actions/workflows/tests.yml/badge.svg)](https://github.com/suhani-k7/arambh-voice-engine/actions/workflows/tests.yml)

An AI-powered voice agent designed to automate the initial borrower onboarding and data collection process for home loans and loans against property (LAP).

The system aims to replace manual telephonic interactions by enabling real-time conversations between borrowers and AI agents. It integrates telephony, speech-to-text, large language models, and text-to-speech technologies to conduct natural conversations, gather relevant borrower information, and convert unstructured conversations into structured data for downstream processing.

## Key Features

* Real-time phone call handling
* Speech-to-text transcription
* AI-driven conversational workflow
* Text-to-speech response generation
* Conversation transcript storage
* Structured borrower data extraction
* Scalable and modular architecture

## Planned Tech Stack

* Python
* FastAPI
* WebSockets
* Twilio / Exotel
* Deepgram (STT)
* Sarvam AI (TTS)
* Grok / Llama (LLM)

## Status

🚧 Currently under development.
## Development Phases

**Phase 0 – Project Setup**: Repository initialized, core clean‑architecture skeleton created, basic FastAPI app scaffolded. ✅ Completed.

**Phase 1 – Telephony Integration**: Twilio/WebSocket audio streaming, `TelephonyHandler` interface and `twilio_handler` implementation. ✅ Completed.

**Phase 2 – Speech‑to‑Text**: Deepgram streaming STT handler, `STTHandler` interface, basic transcript collection. ✅ Completed.

**Phase 3 – Conversational Logic**: `ConversationEngine`, `ConversationState`, LLM response handling, basic turn‑taking flow. ✅ Completed.

**Phase 4 – Text‑to‑Speech**: Sarvam AI TTS handler, audio synthesis back to Twilio. ✅ Completed.

**Phase 5 – Data Extraction & Persistence**: LLM‑based borrower profile extraction (`ExtractorHandler`), SQLite storage (`SQLiteStorageHandler`), API endpoints for retrieving borrower profiles and transcripts. ✅ Completed.

**Phase 6 – E2E testing, latency profiling, timeout recovery, transcript fallbacks**: Comprehensive end‑to‑end test suite, performance benchmarks, graceful degradation strategies, and fallback mechanisms for missing transcripts. ✅ Completed.

**Phase 7 – Deployment**: Backend deployment pipeline, webhook verification steps, environment configuration management, CI/CD integration. ✅ Planned.

**Phase 8 – Analytics**: Call metrics collection, latency monitoring, success/failure rates, conversation analytics dashboard. ✅ Planned.

**Phase 9 – Documentation**: Full developer docs, usage guides, README expansion, API reference. ✅ Planned.
