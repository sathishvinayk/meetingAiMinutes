# 🎙️ meetingAiHackathon - Real-time Meeting Transcription & AI Minutes Generator

> **"Build something that shouldn't work — but does."**  
> *Using weak models (Whisper base.en 244M + Phi-3 3.8B) to build a powerful real-time meeting intelligence platform.*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=flat&logo=docker&logoColor=white)](https://docker.com)
[![React](https://img.shields.io/badge/react-%2320232a.svg?style=flat&logo=react&logoColor=%2361DAFB)](https://reactjs.org/)
[![Go](https://img.shields.io/badge/go-%2300ADD8.svg?style=flat&logo=go&logoColor=white)](https://golang.org/)
[![Python](https://img.shields.io/badge/python-3670A0?style=flat&logo=python&logoColor=white)](https://python.org)

---

## 🎯 Overview

MeetingAiHackathon is a **real-time meeting transcription and AI-powered minutes generation system** that runs entirely locally with zero cloud costs. It captures microphone audio, streams it in chunks, transcribes speech in real-time using Whisper, and generates intelligent meeting minutes (action items, decisions, discussion points, sentiment analysis) using Phi-3 via Ollama.

**The "Wow Gap"** – This system accomplishes what typically requires expensive frontier models (GPT-4, Claude) using only weak, open-source models (244M + 3.8B parameters) through clever engineering.

### Why meetingAiHackathon?

- 🔒 **Privacy First** – Everything runs locally, no data leaves your machine
- 💰 **Zero Cost** – No API fees, no cloud subscriptions
- 🚀 **Real-time** – See transcriptions as you speak (2-3 second latency)
- 🧠 **AI-Powered** – Intelligent minutes generation with action items
- 🐳 **Easy Deployment** – Single command with Docker

---

## 📋 Table of Contents
- [Demo](#-demo)
- [Architecture](#-architecture)
- [Models Used](#-models-used)
- [Features](#-features)
- [Technical Stack](#-technical-stack)
- [Installation](#-installation)
- [Usage](#-usage)
- [Performance](#-performance)
- [Cost Analysis](#-cost-analysis)
- [Limitations & Failures](#-limitations--failures)
- [Future Improvements](#-future--improvements)
- [Troubleshooting](#-troubleshooting)
- [License](#-license)

---

## 🎬 Demo

### Live Demonstration

[🎥 **Click here to watch the demo video**](https://youtu.be/your-demo-link)

### Sample Session
**What the demo shows:**

1. User clicks "Start Meeting" and grants microphone access
2. User speaks a sentence naturally
3. Real-time transcriptions appear every 2-3 seconds
4. User clicks "End Meeting"
5. AI-generated minutes appear with action items, decisions, and sentiment analysis

**Sample Output:**
```text
📝 Transcription: "We need to have a call by this week to discuss the issue."
📝 Transcription: "issues related components connecting front end API."

📊 Meeting Minutes:
✅ Action Items: Have a call by this week to discuss the issue of related components
📋 Decisions: Continue with proposed plan
💬 Discussion: Technical integration discussion
😊 Sentiment: neutral
```

## 🏗 Architecture
---
```text
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Browser   │────▶│   Backend   │────▶│  ML Service │────▶│   Whisper   │
│  (React)    │◀────│    (Go)     │◀────│  (Python)   │     │  base.en    │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
      │                    │                    │                    │
      │ WebSocket          │ gRPC               │ FFmpeg             │
      │ (audio chunks)     │ (streaming)        │ (persistent)       │
      │                    │                    │                    │
      ▼                    ▼                    ▼                    ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Live      │     │  Session    │     │   PCM       │     │   Phi-3     │
│ Transcript  │     │  Management │     │   Chunks    │     │  (Ollama)   │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```
---
## Data Flow:

1. Frontend (React) - Captures microphone audio using MediaRecorder API, sends 3-second WebM chunks via WebSocket
2. Backend (Go) - Manages WebSocket connections, forwards audio chunks to ML service via gRPC
3. ML Service (Python) - Maintains persistent FFmpeg process per session, converts WebM → PCM in real-time
4. Whisper - Transcribes 3-second PCM chunks → real-time text
5. Ollama + Phi-3 - Generates meeting minutes from full transcript at session end
6. Results flow back through the chain to the browser
---
## 🤖 Models Used

| Model | Size on Disk | Parameters | Tier | Location | Purpose | Cost per Meeting |
|-------|--------------|------------|------|----------|---------|------------------|
| **Whisper base.en** | 139 MB | 244M | Tier 2 | Local (CPU) | Real-time speech transcription | **$0** |
| **Phi-3 mini** | 2.03 GB | 3.8B | Tier 3 | Ollama (local CPU) | AI minutes generation | **$0** |
| **FFmpeg** | 10 MB | N/A | N/A | System | Audio conversion (WebM → PCM) | **$0** |

**No frontier models** used – No GPT-4, Claude Opus, Gemini Pro, or any commercial LLM APIs.

**Model Justification:**

* **Whisper base.en** (not tiny, not large) – Balances accuracy (higher than tiny) with speed (faster than large). Runs comfortably on CPU.

* **Phi-3 mini** – Microsoft's 3.8B parameter model that punches above its weight class. Small enough for CPU inference (~2-3 seconds per generation) but capable enough for minutes extraction.

---
## ✨ Features
### Core Features:

* ✅ Real-time audio streaming – 3-second chunks, WebM format
* ✅ Persistent FFmpeg pipeline – Solves the "first chunk only has headers" problem
* ✅ Live transcription – See text appear as you speak (2-3 second latency)
* ✅ Voice Activity Detection (VAD) – Skip silence, reduce hallucinations
* ✅ AI minutes generation – Action items, decisions, discussion points, sentiment
* ✅ Session management – Multiple concurrent meetings supported
* ✅ Zero cloud cost – Everything runs locally

### Technical Highlights:

* ✅ WebSocket – Real-time bidirectional communication
* ✅ gRPC streaming – Efficient backend-to-ML communication
* ✅ Docker Compose – One-command deployment
* ✅ Volume meter – Visual feedback for microphone input
* ✅ Graceful error handling – Session recovery, chunk buffering

---
## 🛠 Technical Stack

| Layer | Technology | Version | Purpose |
|-------|------------|---------|---------|
| **Frontend** | React | 18.2.0 | UI components |
| | WebSocket API | - | Real-time communication |
| | MediaRecorder API | - | Audio capture |
| **Backend** | Go | 1.21 | High concurrency server |
| | gRPC | 1.59.0 | Service-to-service communication |
| | Gorilla WebSocket | 1.5.1 | WebSocket handling |
| **ML Service** | Python | 3.10 | ML inference |
| | OpenAI Whisper | 20231117 | Speech recognition |
| | NumPy | 1.24.3 | Audio data manipulation |
| | FFmpeg | 5.1.2 | Audio conversion (WebM → PCM) |
| **LLM Serving** | Ollama | 0.1.17 | Local model serving |
| | Phi-3 mini | 3.8B | Minutes generation |
| **Deployment** | Docker | 24.0.7 | Containerization |
| | Docker Compose | 2.23.0 | Multi-service orchestration |

## 📦 Installation
### Prerequisites
* Docker and Docker Compose installed
* 4GB+ RAM (8GB recommended for all services)
* 2CPU+ (for Whisper + Phi-3 inference)
* Microphone (built-in or external)

**Quick Start (5 minutes)**
```text
# 1. Clone the repository
git clone https://github.com/yourusername/meetingAiHackathon.git
cd meetingAiHackathon

# 2. Build and start all services
docker-compose up --build

# 3. Wait for model downloads (~1-2 minutes)
#    - Whisper base.en (139MB)
#    - Phi-3 mini (2.03GB) - first run only

# 4. Open browser and navigate to:
#    http://localhost:3000
```

**Manual Setup (without Docker)**
```
# Backend
cd backend
go mod tidy
go build -o backend .
./backend

# ML Service
cd ml-service
pip install -r requirements.txt
python ml_service.py

# Frontend
cd frontend
npm install
npm start

```

## Environment Variables
| Variable | Default | Description | Required |
|----------|---------|-------------|----------|
| `OLLAMA_HOST` | `http://ollama:11434` | Ollama service endpoint | No |
| `WHISPER_MODEL` | `base.en` | Whisper model size (tiny/base/small) | No |
| `SAMPLE_RATE` | `16000` | Audio sample rate in Hz | No |
| `CHUNK_SECONDS` | `3` | Audio chunk duration in seconds | No |
| `VAD_THRESHOLD` | `0.008` | Voice activity detection threshold | No |
| `OLLAMA_TIMEOUT` | `60` | Ollama request timeout in seconds | No |
--- 
## 🎮 Usage
### Starting a Meeting
1. **Click "Start Meeting"** – Browser requests microphone access
2. **Watch the volume meter** – Ensure it shows 20-40% when speaking
3. **Speak clearly** – Normal conversational volume, 3-4 feet from microphone
4. **Watch live transcriptions** – Text appears every 2-3 seconds

### Ending a Meeting
1. Click "End Meeting"
2. Wait 2-3 seconds – Final transcriptions are processed
3. View AI-generated minutes – Action items, decisions, discussion points appear in the right panel
4. Clear meeting – Start a new session with the "Clear" button

### Tips for Best Results
* 🎤 Speak clearly – Enunciate words, avoid mumbling
* 📏 Stay close to microphone – 1-2 feet optimal
* 🔇 Minimize background noise – Fans, keyboards, other conversations
* ⏱️ Speak for at least 5 seconds – Short utterances may be missed
* 🔄 Use the volume meter – If it's below 10%, speak louder or move closer

---
## 📊 Performance
### Benchmarks (on 8-core CPU, 16GB RAM)
### Transcription Latency
| Phase | Duration | Cumulative |
|-------|----------|------------|
| Audio capture | 3 seconds (chunk) | 3.00s |
| WebSocket send | <50ms | 3.05s |
| gRPC forward | <10ms | 3.06s |
| FFmpeg conversion | <100ms | 3.16s |
| Whisper inference | 1-2 seconds | 4.16-5.16s |
| Return to UI | <50ms | 4.21-5.21s |
--- 

### **Average**

| Model | Load Time (First) | Load Time (Cached) | Inference Time | Memory Usage | CPU Usage |
|-------|-------------------|-------------------|----------------|--------------|-----------|
| Whisper base.en | 51 seconds | 2 seconds | 1-2s/chunk | 500 MB | 60-80% |
| Phi-3 mini | 3 seconds | 3 seconds | 11s/generation | 3.5 GB | 80-100% |

---

## 💰 Cost Analysis
## Infrastructure Cost: $0.00

| Component | Cost | Justification |
|-----------|------|---------------|
| Whisper base.en (244M) | **$0** | Open source, runs locally on CPU |
| Phi-3 mini (3.8B) via Ollama | **$0** | Open source, runs locally on CPU |
| FFmpeg | **$0** | Open source system utility |
| React frontend | **$0** | Open source framework |
| Go backend | **$0** | Open source language |
| Docker | **$0** | Free community edition |
| WebSocket & gRPC | **$0** | Built into languages |
| **Total per meeting** | **$0.00** | No API calls, no cloud services |
| **Total per month** | **$0.00** | Unlimited meetings |
| **Total per year** | **$0.00** | No subscription, no hidden fees |

### Hidden Costs Considered

| Potential Cost | meetingAiHackathon | Commercial Alternatives |
|----------------|--------------|------------------------|
| API fees per minute | **$0** | $0.01-0.03/minute |
| Cloud storage | **$0** | $10-20/month |
| User licenses | **$0** | $15-20/user/month |
| Data egress | **$0** | $0.10-0.50/GB |
| Model hosting | **$0** | $50-200/month |
| **Total** | **$0** | **$200-500+/month** |

### Feature Comparison

| Feature | meetingAiHackathon | Otter.ai | Fireflies | Zoom | MS Teams |
|---------|--------------|----------|-----------|------|----------|
| Real-time transcription | ✅ | ✅ | ✅ | ✅ | ✅ |
| AI action items | ✅ | ✅ | ✅ | ✅ | ✅ |
| Speaker diarization | ❌ | ✅ | ✅ | ✅ | ✅ |
| Local processing | ✅ | ❌ | ❌ | ❌ | ❌ |
| Zero cost | ✅ | ❌ | ❌ | ❌ | ❌ |
| Open source | ✅ | ❌ | ❌ | ❌ | ❌ |
| Offline capable | ✅ | ❌ | ❌ | ❌ | ❌ |
| Export formats | ❌ | ✅ | ✅ | ✅ | ✅ |


### Annual Savings with meetingAiHackathon
**Total savings after 1 year:** $1800-4800
---
## ⚠️ Limitations & Failures
### Technical Limitations
1. **Single meeting focus** – The system is designed for one meeting at a time per browser. Multiple tabs work independently.
2. **No speaker diarization** – Can't distinguish between different speakers (Whisper limitation).
3. **English only** – Whisper supports 97 languages, but Phi-3 prompt is English. Language switching would require prompt engineering.
4. **No punctuation restoration** – Real-time chunks may cut mid-sentence, resulting in missing periods/capitals.
5. **CPU-only inference** – No GPU acceleration available in the demo environment. GPU would improve latency significantly.

## Documented Failures (During Development)
Issue	Root Cause	Solution
First chunk only had WebM headers	MediaRecorder chunks are incomplete WebM files	Persistent FFmpeg pipeline
FFmpeg conversion failed	Second chunk didn't have headers	Keep FFmpeg running across chunks
Whisper output "Thank you. That's awesome."	Audio too quiet	Added VAD + amplification
Empty transcript in minutes	Backend only stored is_final=true transcriptions	Store all non-empty transcriptions
Ollama JSON parsing errors	Phi-3 returned malformed JSON	Added fallback extraction with regex
Session ID mismatch	Client used different session ID for end_meeting	Fixed session ID propagation
WebSocket disconnections	React StrictMode double-mounting	Added reconnection logic

## Known Issues
* 🐛 First chunk may be delayed – MediaRecorder buffer fills slowly on some systems
* 🐛 Very fast speech may be truncated – 3-second chunks may cut mid-word
* 🐛 Background music confuses Whisper – Tries to transcribe instruments as speech
* 🐛 Phi-3 occasionally returns invalid JSON – Fallback extraction handles it

## 🔮 Future Improvements
### Short-term (Next Sprint)
* Speaker diarization – Use pyannote.audio to distinguish speakers
* [ Live minutes update – Update minutes incrementally during meeting
* Export formats – PDF, DOCX, Markdown, plain text
* Search transcripts – Full-text search across past meetings
* Edit & correct – Allow users to correct transcriptions

### Medium-term
* Real-time translation – Translate transcriptions to other languages
* Meeting summaries – Generate executive summaries automatically
* Action item tracking – Assignment tracking and completion status
* Calendar integration – Auto-detect meeting times and join
* Custom prompts – Allow users to customize minutes generation

### Long-term (With funding)
* GPU acceleration – Reduce latency by 3-5x
* Edge deployment – Run on Raspberry Pi or Jetson Nano
* Cloud sync – Optional encrypted cloud backup
* CRM integration – Auto-create tasks in Jira, Asana, Notion
* Meeting insights – Talk time analysis, filler word detection, engagement metrics

--- 
## 🔧 Troubleshooting
## Common Issues and Solutions

| Issue | Symptoms | Root Cause | Solution |
|-------|----------|------------|----------|
| **No transcription** | "No speech detected" message | Microphone permission denied, audio too quiet, or no speech | Check volume meter (should show 10-40%), allow microphone access, speak louder/closer |
| **WebSocket disconnected** | Error 1006, connection lost | Network interruption, browser tab inactive, React StrictMode | Refresh page, clear browser cache, check firewall |
| **Whisper not loading** | Model download stuck at 0% | Internet connection issue, out of memory | Check internet, increase Docker memory to 4GB+, restart containers |
| **Minutes not generating** | End meeting but no minutes appear | Backend didn't receive end_meeting, transcript empty | Wait 2-3 seconds after ending, check backend logs |
| **High CPU usage (100%)** | System slowdown, fan noise | Normal during transcription and minutes generation | Reduce concurrent meetings, upgrade hardware |
| **Out of memory** | Containers crash, Docker fails | Not enough RAM allocated | Increase Docker memory limit to 6GB+, close other apps |
| **FFmpeg conversion failed** | "Audio conversion failed" error | Corrupted WebM data, missing FFmpeg | Check browser console, reinstall FFmpeg in container |
| **Ollama timeout** | Minutes generation takes >30 seconds | Phi-3 first inference is slow | Increase timeout to 60s, keep Ollama running |
| **Duplicate transcriptions** | Same text appears twice in UI | Whisper sending duplicate chunks | Added duplicate detection in backend |
| **Microphone not detected** | No devices found, error | Browser permission denied, no microphone | Check system settings, allow microphone in browser, restart browser |


---
## Debugging Commands
```text
# View all logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f ml-service
docker-compose logs -f backend
docker-compose logs -f frontend

# Restart a single service
docker-compose restart ml-service

# Rebuild and restart
docker-compose up --build --force-recreate

# Check container health
docker-compose ps

# Access container shell
docker exec -it meetingAiHackathon-ml /bin/bash

# Test FFmpeg conversion manually
ffmpeg -i test.webm -ar 16000 -ac 1 test.wav
```

## Log File Locations
```text
Service	Log Location	Contents
ML Service	docker logs meetingAiHackathon-ml	Model loading, transcription, FFmpeg
Backend	docker logs meetingAiHackathon-backend	WebSocket, gRPC, session management
Frontend	Browser console (F12)	Audio capture, WebSocket messages
Ollama	docker logs meetingAiHackathon-ollama	Model loading, inference
```

## 📁 Project Structure
```text
meetingAiHackathon/
├── frontend/                 # React app
│   ├── public/               # Static files
│   ├── src/
│   │   ├── App.js           # Main React component
│   │   ├── App.css          # Styling
│   │   └── index.js         # Entry point
│   ├── Dockerfile           # Frontend container
│   └── package.json         # Dependencies
│
├── backend/                  # Go service
│   ├── main.go              # WebSocket + gRPC server
│   ├── pb/                  # Protobuf generated code
│   ├── meeting.proto        # gRPC protocol definition
│   ├── Dockerfile           # Backend container
│   └── go.mod               # Go dependencies
│
├── ml-service/               # Python ML service
│   ├── ml_service.py        # Whisper + FFmpeg + Ollama client
│   ├── meeting_pb2.py       # Protobuf generated
│   ├── meeting_pb2_grpc.py  # gRPC generated
│   ├── requirements.txt     # Python dependencies
│   └── Dockerfile           # ML container
│
├── docker-compose.yml       # Service orchestration
└── README.md                # This file
```

## 🏁 Conclusion
**meetingAiHackathon proves that you don't need expensive frontier models to build powerful AI products**. With clever engineering (persistent FFmpeg, VAD, chunk-based streaming), weak models (Whisper 244M + Phi-3 3.8B) can deliver real-time transcription and intelligent minutes generation at zero cost.

**The "wow gap"** – What started as "that shouldn't work" became a fully functional, production-ready meeting intelligence platform that rivals paid services.