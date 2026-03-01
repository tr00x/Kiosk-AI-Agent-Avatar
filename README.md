# Kiosk AI Agent Avatar

Real-time conversational AI kiosk with a lip-synced avatar for dental clinic patient self-service. Patients interact with **Emma** — an AI-powered virtual receptionist — using natural voice conversation, while seeing a realistic animated avatar on screen.

Built on [Pipecat](https://github.com/pipecat-ai/pipecat) framework with WebRTC transport for ultra-low latency audio/video streaming.

---

## Core Capabilities

### Real-Time Voice Conversation
- Continuous, natural speech recognition powered by **OpenAI Realtime STT** (`gpt-4o-transcribe`)
- Intelligent conversation management via **OpenAI GPT-4o** LLM with function calling
- High-quality text-to-speech using **Fish Speech v1.4** running locally for minimal latency
- Local **Silero VAD** (Voice Activity Detection) — voice activity is processed on-device, not sent to cloud for detection
- Responses are kept short and conversational (max ~20 words per turn) for a natural kiosk experience

### Lip-Synced AI Avatar
- Photorealistic avatar rendered in real-time by **Simli AI**
- TTS audio is streamed directly to Simli, which returns lip-synced video frames
- 512x512 resolution at 30 FPS via WebRTC
- Idle loop video plays when no active session, seamless transition to live avatar on conversation start
- Avatar renders in the browser with no plugins or installs required

### Patient Verification & Identity
- Voice-based patient lookup: patient states their name and date of birth
- Verified against **Open Dental** practice management database in real-time
- Natural date parsing — understands "March fifteenth nineteen eighty-five", "03/15/1985", and other formats
- Up to 3 verification attempts with friendly re-prompts before redirecting to front desk staff
- HIPAA-compliant audit logging for every data access event

### Account Balance Inquiry
- Retrieves patient balance from Open Dental after identity verification
- Calculates net balance: `Total Balance - Insurance Estimate`
- Displays balance in a slide-in info panel on screen while Emma reads it aloud
- Shows insurance pending amounts when applicable

### Appointment Management
- **View upcoming appointments** — lists up to 5 scheduled visits with date, time, provider name, procedure, and room
- **Book new appointments** — creates appointment requests in a dedicated `kiosk_appointment_requests` table with auto-generated confirmation numbers (e.g., `REQ-0001`). Staff reviews and confirms
- **SMS reminders** — sends appointment reminder to patient's phone on file (phone number is masked in UI: `+1***XXXX`)
- Procedure codes are automatically translated to human-readable names (e.g., `ImpCr` → `Implant Crown`, `RCT` → `Root Canal`)

### Manual Check-In Sidebar
- Staff-accessible side panel (slide-in from left edge) for non-voice check-in
- Search by last name + date of birth
- Displays patient card with appointment details
- 30-second auto-reset countdown for kiosk security
- Privacy-safe: returns an error if multiple patients match the same criteria

### Session Management
- Single-session enforcement — only one active conversation at a time to prevent conflicts
- 60-second silence timeout with automatic session termination
- Graceful WebRTC disconnection handling and pipeline cleanup
- 2-second stabilization delay after WebRTC connect before greeting plays

### Multilingual Support
- Language toggle in the UI header: English, Spanish, Russian
- Frontend labels and UI text adapt to selected language
- Language preference stored in `localStorage` for persistence

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Browser (Kiosk)                    │
│                                                      │
│  ┌──────────┐  ┌────────────┐  ┌──────────────────┐  │
│  │  Avatar   │  │ Transcript │  │   Info Panels    │ │
│  │  Video    │  │  Overlay   │  │ (Balance, Appts) │ │
│  └────▲─────┘  └─────▲──────┘  └───────▲──────────┘  │
│       │              │                  │            │
│       │         WebSocket (events)      │            │
│       │              │                  │            │
│  WebRTC (audio/video)│                  │            │
└───────┼──────────────┼──────────────────┼────────────┘
        │              │                  │
┌───────┼──────────────┼──────────────────┼────────────┐
│       ▼              ▼                  │  Backend   │
│  ┌─────────────────────────────────┐    │            │
│  │        Pipecat Pipeline         │    │            │
│  │                                 │    │            │
│  │  Transport In (mic audio)       │    │            │
│  │       ↓                         │    │            │
│  │  Silero VAD (local)             │    │            │
│  │       ↓                         │    │            │
│  │  OpenAI Realtime STT            │    │            │
│  │       ↓                         │    │            │
│  │  LLM Context Aggregator         │    │            │
│  │       ↓                         │    │            │
│  │  OpenAI GPT-4o (+ functions)  ──┼────┘            │
│  │       ↓                         │                 │
│  │  Fish Speech TTS (local)        │                 │
│  │       ↓                         │                 │
│  │  Simli AI Avatar (lip-sync)     │                 │
│  │       ↓                         │                 │
│  │  Transport Out (video + audio)  │                 │
│  └─────────────────────────────────┘                 │
│                    │                                 │
│              ┌─────▼─────┐                           │
│              │ Open Dental│                          │
│              │   MySQL    │                          │
│              └────────────┘                          │
└──────────────────────────────────────────────────────┘
```

### Conversation Flow (Pipecat Flows)

```
greeting → verify_dob → main_menu ──→ check_balance ──→ main_menu / goodbye
                │              │──→ view_appointments ─→ main_menu / goodbye
                │              │──→ start_booking ─────→ main_menu / goodbye
                │              └──→ send_reminder ─────→ main_menu / goodbye
                │
                └─→ not_found (retry up to 3x) → see_receptionist
```

Each node includes a system prompt defining Emma's persona, task-specific instructions, available LLM functions, and pre/post actions (e.g., TTS greetings, session cleanup).

---

## Tech Stack

| Component | Technology | Details |
|-----------|-----------|---------|
| **Framework** | [Pipecat](https://github.com/pipecat-ai/pipecat) | Real-time conversational AI pipeline framework |
| **LLM** | OpenAI GPT-4o | Function calling for database queries |
| **Speech-to-Text** | OpenAI Realtime STT | `gpt-4o-transcribe` model, multilingual |
| **Text-to-Speech** | Fish Speech v1.4 | Local server, 44.1 kHz, custom voice cloning support |
| **Avatar** | Simli AI | Real-time lip-synced video generation |
| **VAD** | Silero VAD | Local voice activity detection (confidence 0.8) |
| **Transport** | WebRTC (aiortc) | Peer-to-peer audio/video, SmallWebRTC transport |
| **Web Server** | aiohttp | Async Python HTTP server |
| **Database** | MySQL | Open Dental practice management system |
| **Frontend** | Vanilla HTML/CSS/JS | Single-page kiosk application, dark theme |

---

## UI & Design

- **Full-screen kiosk layout** — designed for touch-screen displays
- **Dark theme** — `#0a0a0a` background with glassmorphism effects (backdrop blur, semi-transparent panels)
- **Teal accent** (`#288d89`) with green/red status indicators
- **Transcript overlay** — user speech in green italic, bot responses in white. Auto-fades after ~5 seconds
- **Slide-in info panels** — balance, appointments, booking confirmations appear top-right with smooth animation. Auto-hide after 8 seconds
- **Status indicator** — green (listening), blue (processing), amber (error)
- **Loading overlay** — spinner with progress steps: Initializing → Connecting to Avatar → Waiting for Response
- **Stop button** — red circle at bottom center to end conversation at any time

---

## WebSocket Events

The backend broadcasts real-time events via WebSocket (`/events`) for UI updates:

| Event | Payload | Description |
|-------|---------|-------------|
| `call_started` | — | Session began |
| `call_ended` | `{ reason }` | Session ended |
| `user_transcript` | `{ text }` | User speech transcription |
| `bot_transcript` | `{ text }` | Bot response text |
| `patient_verified` | `{ name, id }` | Patient identity confirmed |
| `balance` | `{ amount, insurance }` | Account balance data |
| `appointments` | `[{ date, time, provider, procedure }]` | Upcoming appointments |
| `booking_confirmed` | `{ confirmation_number }` | Appointment request created |
| `error` | `{ message }` | Error notification |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Serves the kiosk UI (`index.html`) |
| `POST` | `/api/offer` | WebRTC SDP offer/answer exchange |
| `POST` | `/api/ice-candidate` | WebRTC ICE candidate handling |
| `GET` | `/events` | WebSocket endpoint for real-time UI events |
| `GET` | `/health` | Health check |

---

## Setup

### Prerequisites

- Python 3.12+
- MySQL server with Open Dental database
- Fish Speech v1.4 server
- API keys: OpenAI, Simli AI

### Environment Variables

Create a `.env` file:

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

### Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Running

Terminal 1 — Fish Speech TTS server:
```bash
python tools/api.py --listen 127.0.0.1:8090 --device mps --mode tts
```

Terminal 2 — Kiosk application:
```bash
python main.py
```

Open `http://localhost:8080` in a browser (or on the kiosk display).

---

## Project Structure

```
├── main.py          # Web server, session management, WebRTC signaling
├── agent.py         # Pipecat pipeline construction (STT → LLM → TTS → Avatar)
├── flow.py          # Conversation flow nodes (greeting, verification, menu)
├── tools.py         # Database tools (patient lookup, balance, appointments, booking)
├── fish_tts.py      # Custom Pipecat TTS service for Fish Speech v1.4
├── db.py            # MySQL connection pool with retry logic
├── index.html       # Kiosk frontend (single-page app)
├── requirements.txt # Python dependencies
└── .env             # Environment variables (not committed)
```

---

## Security & Compliance

- **HIPAA audit logging** — every patient data access is recorded in `kiosk_audit_log` with timestamp, action, and patient ID
- **Patient verification required** — no data is shown until identity is confirmed via name + date of birth
- **Phone number masking** — displayed as `+1***XXXX` in UI and logs
- **Privacy-safe search** — manual check-in returns an error if multiple patients match, preventing data leakage
- **Single-session isolation** — only one active conversation at a time
- **Auto-timeout** — sessions end after 60 seconds of silence

---

## Avatar Idle Video

The avatar idle loop video (15 MB) is not included in this repository. You can download it and place it in the project root:

[Download idle video (MP4)](https://storage.googleapis.com/simliai2.appspot.com/videos/f0ba4efe-7946-45de-9955-c04a04c367b9.mp4)

> **Note:** Simli AI provides 50 free minutes per month — more than enough for testing and evaluation.

---

## Looking for a Technical Partner?

I built this end-to-end — from real-time voice pipeline and avatar integration to the database layer and kiosk UI. If your company needs a production-grade conversational AI solution but doesn't have the engineering talent to build one, let's talk.

I'm available for contract work, consulting, and full builds.

**Get in touch:**

[![Email](https://img.shields.io/badge/Email-tr00x%40proton.me-blue?style=for-the-badge&logo=protonmail&logoColor=white)](mailto:tr00x@proton.me)
[![Telegram](https://img.shields.io/badge/Telegram-@tr00x-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/tr00x)

---

## License

All rights reserved.
