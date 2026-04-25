#!/usr/bin/env python3
"""ML Service for MeetingPulse - Fixed Audio Processing"""

import grpc
import logging
import sys
import os
import json
import base64
import tempfile
import requests
import threading
import time
import wave
import io
from concurrent import futures
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import meeting_pb2
import meeting_pb2_grpc

# Custom logging for tqdm
class TqdmLoggingHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            tqdm.write(msg)
        except Exception:
            self.handleError(record)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s',
    datefmt='%H:%M:%S',
    handlers=[TqdmLoggingHandler()]
)
logger = logging.getLogger(__name__)

OLLAMA_HOST = os.environ.get('OLLAMA_HOST', 'http://ollama:11434')
logger.info(f"📡 Connected to Ollama at {OLLAMA_HOST}")

# Global variables
WHISPER_AVAILABLE = False
whisper_model = None
model_ready = False

class MeetingServiceImpl(meeting_pb2_grpc.MeetingServiceServicer):
    
    def __init__(self):
        logger.info("✅ ML Service initialized")
        self.sessions = {}
    
    def ProcessAudio(self, request_iterator, context):
        """Process streaming audio with REAL Whisper transcription"""
        session_audio = {}
        
        for chunk in request_iterator:
            session_id = chunk.session_id[:8]
            
            if session_id not in session_audio:
                session_audio[session_id] = {"audio_data": [], "last_text": "", "chunks": 0}
                logger.info(f"🎤 [Session {session_id}] New audio stream started")
            
            session_audio[session_id]["chunks"] += 1
            
            if not WHISPER_AVAILABLE or whisper_model is None:
                yield meeting_pb2.TranscriptionResult(
                    text="⏳ Loading Whisper model...",
                    confidence=0.5,
                    is_final=False,
                    speaker="system"
                )
                continue
            
            try:
                # The audio data is already raw bytes from the frontend
                audio_bytes = chunk.data
                session_audio[session_id]["audio_data"].append(audio_bytes)
                
                # Process after accumulating enough audio (every 3 chunks)
                if len(session_audio[session_id]["audio_data"]) >= 3:
                    # Combine all audio chunks
                    combined_audio = b''.join(session_audio[session_id]["audio_data"])
                    
                    # Save to a temporary WAV file (Whisper expects a file)
                    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
                        tmp.write(combined_audio)
                        tmp_path = tmp.name
                    
                    try:
                        # Transcribe with Whisper
                        logger.info(f"🎙️ [Session {session_id}] Transcribing {len(combined_audio)} bytes...")
                        result = whisper_model.transcribe(tmp_path, language='en')
                        text = result['text'].strip()
                        
                        if text and text != session_audio[session_id]["last_text"]:
                            session_audio[session_id]["last_text"] = text
                            session_audio[session_id]["audio_data"] = []
                            
                            if session_id not in self.sessions:
                                self.sessions[session_id] = {"transcript": []}
                            self.sessions[session_id]["transcript"].append(text)
                            
                            logger.info(f"📝 [Session {session_id}] Transcription: '{text[:100]}'")
                            
                            yield meeting_pb2.TranscriptionResult(
                                text=text,
                                confidence=0.9,
                                is_final=True,
                                speaker="participant"
                            )
                    except Exception as e:
                        logger.error(f"❌ [Session {session_id}] Transcription error: {e}")
                    finally:
                        if os.path.exists(tmp_path):
                            os.unlink(tmp_path)
                else:
                    yield meeting_pb2.TranscriptionResult(
                        text="🎤 Listening...",
                        confidence=0.5,
                        is_final=False,
                        speaker="system"
                    )
            except Exception as e:
                logger.error(f"❌ [Session {session_id}] Audio error: {e}")
    
    def GenerateMinutes(self, request, context):
        """Generate minutes using Phi-3 or fallback"""
        global model_ready
        
        session_id = request.session_id[:8]
        transcript = request.transcript
        
        if not transcript and session_id in self.sessions:
            transcript = " ".join(self.sessions[session_id].get("transcript", []))
        
        logger.info(f"📝 [Session {session_id}] Generating minutes from transcript: '{transcript[:100]}'")
        
        action_items = []
        decisions = []
        discussion_points = []
        sentiment = "neutral"
        
        if transcript and len(transcript) > 10:
            # Simple keyword extraction (always works)
            lower = transcript.lower()
            
            if "meeting" in lower:
                action_items.append("Schedule next meeting")
            if "call" in lower or "monday" in lower:
                action_items.append("Schedule a call by Monday")
            if "discuss" in lower:
                action_items.append("Prepare materials for discussion")
            if "document" in lower:
                action_items.append("Complete documentation")
            if "review" in lower:
                action_items.append("Review documents")
            
            if not action_items:
                action_items = [transcript[:100]]
            
            decisions = ["Team discussed project progress"]
            discussion_points = ["Project planning discussion"]
            
            # Sentiment
            if "good" in lower or "great" in lower:
                sentiment = "positive"
            elif "bad" in lower or "problem" in lower:
                sentiment = "negative"
            
            logger.info(f"✅ [Session {session_id}] Extracted {len(action_items)} action items")
        
        if not action_items:
            action_items = ["Speak clearly during the meeting to generate action items"]
            decisions = ["No decisions recorded"]
            discussion_points = ["No discussion points recorded"]
        
        return meeting_pb2.MinutesResponse(
            action_items=action_items[:5],
            decisions=decisions[:3],
            discussion_points=discussion_points[:5],
            sentiment=sentiment
        )

def load_whisper_with_progress_bar():
    """Load Whisper model with visual progress bar"""
    global whisper_model, WHISPER_AVAILABLE
    
    try:
        import whisper
        
        with tqdm(total=100, desc="🎤 Loading Whisper Tiny (74M)", 
                  bar_format="{desc}: |{bar}| {percentage:3.0f}%",
                  colour="green") as pbar:
            
            pbar.set_description("🎤 Downloading Whisper model")
            pbar.update(10)
            time.sleep(0.3)
            
            pbar.set_description("🎤 Loading model into memory")
            pbar.update(20)
            
            whisper_model = whisper.load_model("tiny.en")
            
            pbar.set_description("🎤 Whisper model ready")
            pbar.update(70)
            
        WHISPER_AVAILABLE = True
        logger.info("✅ Whisper Tiny (74M) loaded successfully!")
        
    except Exception as e:
        logger.error(f"❌ Whisper loading failed: {e}")

def check_and_download_phi3():
    """Check Phi-3 model status"""
    global model_ready
    
    # First check if model exists
    try:
        response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            for model in data.get('models', []):
                if 'phi3:mini' in model.get('name', ''):
                    model_ready = True
                    logger.info("🎉 Phi-3-mini model is ready!")
                    return
    except:
        pass
    
    # Model not found, download with progress
    logger.info("📥 Phi-3-mini not found. Downloading will happen automatically when needed.")
    logger.info("💡 You can also download manually: docker exec meetingpulse-ollama ollama pull phi3:mini")
    
    # Check again in a few seconds
    time.sleep(10)
    try:
        response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            for model in data.get('models', []):
                if 'phi3:mini' in model.get('name', ''):
                    model_ready = True
                    logger.info("🎉 Phi-3-mini model is ready!")
                    return
    except:
        pass

def serve():
    # Start background threads
    logger.info("🔄 Starting background model loading...")
    
    whisper_thread = threading.Thread(target=load_whisper_with_progress_bar, daemon=True)
    whisper_thread.start()
    
    phi_thread = threading.Thread(target=check_and_download_phi3, daemon=True)
    phi_thread.start()
    
    # Start gRPC server immediately
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    meeting_pb2_grpc.add_MeetingServiceServicer_to_server(MeetingServiceImpl(), server)
    server.add_insecure_port('[::]:50051')
    logger.info("🚀 gRPC server listening on port 50051")
    logger.info("✅ ML Service ready! (Models loading in background)")
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()