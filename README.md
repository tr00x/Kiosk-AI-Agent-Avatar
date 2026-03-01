<div align="center">

# Kiosk AI Agent Avatar

### Real-time AI receptionist with lip-synced avatar for patient self-service

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Pipecat](https://img.shields.io/badge/Pipecat-Framework-FF6B35?style=flat-square)](https://github.com/pipecat-ai/pipecat)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o-412991?style=flat-square&logo=openai&logoColor=white)](https://openai.com)
[![WebRTC](https://img.shields.io/badge/WebRTC-Realtime-333333?style=flat-square&logo=webrtc&logoColor=white)](https://webrtc.org)
[![Simli](https://img.shields.io/badge/Simli_AI-Avatar-00D4AA?style=flat-square)](https://simli.com)
[![License](https://img.shields.io/badge/License-All_Rights_Reserved-red?style=flat-square)]()

<br>

**Patients walk up to a kiosk, tap "Start", and talk to Emma — an AI receptionist who sees them, hears them, and handles everything from identity verification to appointment booking. No waiting in line. No front desk bottleneck.**

<br>

[Features](#-what-it-does) · [Architecture](#-architecture) · [Tech Stack](#-tech-stack) · [Setup](#-setup) · [Contact](#-hire-me)

</div>

<br>

---

<br>

## What it does

<table>
<tr>
<td width="50%">

### Voice Conversation
Continuous, natural speech interaction powered by **OpenAI Realtime STT** and **GPT-4o**. Local **Fish Speech** TTS for minimal latency. Local **Silero VAD** — voice activity never leaves the device.

### Lip-Synced Avatar
Photorealistic avatar by **Simli AI** — lip-syncs in real-time to speech output. 512x512 @ 30 FPS streamed via WebRTC. Zero plugins, runs in any browser.

### Patient Verification
"Hi, my name is John Smith, born March 15, 1985" — Emma looks up the patient in **Open Dental** database, verifies identity, and unlocks their records. Natural date parsing, 3 retry attempts, HIPAA audit logging.

</td>
<td width="50%">

### Account & Appointments
Check balance (net of insurance estimates), view upcoming visits with provider/procedure/room details, book new appointments (auto-generated confirmation numbers), send SMS reminders.

### Manual Check-In
Staff-accessible sidebar for non-voice check-in. Search by last name + DOB, view patient card, 30-second auto-reset for kiosk security.

### Session Control
Single-session enforcement, 60-second silence timeout, graceful WebRTC teardown. Multilingual UI — English, Spanish, Russian.

</td>
</tr>
</table>

<br>

---

<br>

## Architecture

```
  Browser (Kiosk)                          Backend (Python / aiohttp)
 ┌────────────────┐                       ┌──────────────────────────────────┐
 │                │   WebRTC audio/video  │                                  │
 │  Avatar Video  │◄─────────────────────►│  Pipecat Pipeline                │
 │  Transcript    │                       │                                  │
 │  Info Panels   │   WebSocket events    │  Mic ► Silero VAD ► OpenAI STT   │
 │  Manual Sidebar│◄─────────────────────►│       ► GPT-4o (+ functions)     │
 │                │                       │       ► Fish Speech TTS          │
 └────────────────┘                       │       ► Simli AI Avatar          │
                                          │       ► WebRTC Out               │
                                          │              │                   │
                                          │        ┌─────▼──────┐            │
                                          │        │Open Dental │            │
                                          │        │  MySQL DB  │            │
                                          │        └────────────┘            │
                                          └──────────────────────────────────┘
```

### Conversation Flow

```
greeting ► verify_dob ► main_menu ──► check_balance ──► main_menu / goodbye
                │              ├────► view_appointments ► main_menu / goodbye
                │              ├────► start_booking ────► main_menu / goodbye
                │              └────► send_reminder ────► main_menu / goodbye
                │
                └──► not_found (retry up to 3x) ► see_receptionist
```

Each node carries its own system prompt (Emma's persona), task instructions, LLM function schemas, and pre/post actions.

<br>

---

<br>

## Tech Stack

| Layer | Technology | Why |
|:------|:-----------|:----|
| **AI Framework** | [Pipecat](https://github.com/pipecat-ai/pipecat) | Modular real-time pipeline for voice AI agents |
| **LLM** | OpenAI GPT-4o | Function calling for structured DB queries |
| **Speech-to-Text** | OpenAI Realtime STT | `gpt-4o-transcribe` — fast, multilingual |
| **Text-to-Speech** | Fish Speech v1.4 | Runs locally — zero network latency, voice cloning support |
| **Avatar** | Simli AI | Real-time lip-sync from audio stream |
| **VAD** | Silero VAD | On-device voice detection, no cloud dependency |
| **Transport** | WebRTC (aiortc) | Sub-second peer-to-peer audio/video |
| **Server** | aiohttp | Async Python, handles WebRTC signaling + WebSocket events |
| **Database** | MySQL (Open Dental) | Direct queries against dental practice management system |
| **Frontend** | Vanilla HTML/CSS/JS | Single-page kiosk app, dark glassmorphism theme |

<br>

---

<br>

## UI & Design

| Element | Details |
|:--------|:--------|
| **Layout** | Full-screen kiosk, designed for touch displays |
| **Theme** | Dark (`#0a0a0a`) with glassmorphism — backdrop blur, semi-transparent panels |
| **Accent** | Teal `#288d89` with green/red status indicators |
| **Transcript** | User speech in green italic, bot in white — auto-fades after 5s |
| **Info panels** | Slide-in from top-right (balance, appointments, confirmations) — auto-hide after 8s |
| **Status dot** | Green = listening, Blue = processing, Amber = error |
| **Controls** | "Tap to Start" button, red stop circle, language toggle (EN/ES/RU) |

<br>

---

<br>

## WebSocket Events

Real-time UI updates via `/events`:

| Event | Payload | Description |
|:------|:--------|:------------|
| `call_started` | — | Session began |
| `call_ended` | `{ reason }` | Session terminated |
| `user_transcript` | `{ text }` | Live user speech |
| `bot_transcript` | `{ text }` | Bot response text |
| `patient_verified` | `{ name, id }` | Identity confirmed |
| `balance` | `{ amount, insurance }` | Account balance |
| `appointments` | `[{ date, time, provider, procedure }]` | Upcoming visits |
| `booking_confirmed` | `{ confirmation_number }` | New booking created |
| `error` | `{ message }` | Error notification |

<br>

---

<br>

## API Endpoints

| Method | Path | Description |
|:-------|:-----|:------------|
| `GET` | `/` | Kiosk UI |
| `POST` | `/api/offer` | WebRTC SDP exchange |
| `POST` | `/api/ice-candidate` | ICE candidate handling |
| `GET` | `/events` | WebSocket for real-time events |
| `GET` | `/health` | Health check |

<br>

---

<br>

## Setup

### Prerequisites

- Python 3.12+
- MySQL with Open Dental database
- Fish Speech v1.4 server
- API keys: OpenAI, Simli AI

### Environment

```env
OPENAI_API_KEY=sk-...
SIMLI_API_KEY=...
SIMLI_FACE_ID=...

DB_HOST=...
DB_PORT=3306
DB_USER=...
DB_PASSWORD=...
DB_NAME=opendental

# Optional
FISH_SPEECH_URL=http://localhost:8090
FISH_SPEECH_REF=<speaker-reference-id>
```

### Install & Run

```bash
# Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Terminal 1 — TTS server
python tools/api.py --listen 127.0.0.1:8090 --device mps --mode tts

# Terminal 2 — Kiosk
python main.py
# → http://localhost:8080
```

<br>

---

<br>

## Project Structure

```
├── main.py            Web server, sessions, WebRTC signaling
├── agent.py           Pipecat pipeline (STT → LLM → TTS → Avatar)
├── flow.py            Conversation nodes (greeting → verify → menu)
├── tools.py           DB tools (patient lookup, balance, appointments, booking)
├── fish_tts.py        Custom TTS service for Fish Speech v1.4
├── db.py              MySQL connection pool with retry
├── index.html         Kiosk frontend (single-page dark theme app)
├── requirements.txt   Python dependencies
└── .env               API keys & config (not committed)
```

<br>

---

<br>

## Security & Compliance

| Measure | Implementation |
|:--------|:---------------|
| **HIPAA audit trail** | Every data access logged to `kiosk_audit_log` with timestamp, action, patient ID |
| **Identity verification** | Name + DOB required before any data is shown |
| **Phone masking** | Displayed as `+1***XXXX` in UI and logs |
| **Privacy-safe search** | Returns error if multiple patients match — prevents data leakage |
| **Session isolation** | One active conversation at a time |
| **Auto-timeout** | 60 seconds of silence = session ends |

<br>

---

<br>

## Avatar Idle Video

The idle loop video (15 MB) is not included in this repo. Download and place in the project root:

> **[Download idle video (MP4)](https://storage.googleapis.com/simliai2.appspot.com/videos/f0ba4efe-7946-45de-9955-c04a04c367b9.mp4)**

Simli AI provides **50 free minutes/month** — more than enough for testing.

<br>

---

<br>

<div align="center">

## Hire Me

I built this entire system solo — real-time voice pipeline, avatar integration,
database layer, HIPAA compliance, and kiosk UI.

**If your company needs production-grade conversational AI but lacks the engineering team to build it — I'm your guy.**

Contract work · Consulting · Full builds

<br>

[![Email](https://img.shields.io/badge/tr00x@proton.me-black?style=for-the-badge&logo=protonmail&logoColor=white)](mailto:tr00x@proton.me)&nbsp;&nbsp;&nbsp;[![Telegram](https://img.shields.io/badge/@tr00x-black?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/tr00x)

<br>

---

**All rights reserved.**

</div>
