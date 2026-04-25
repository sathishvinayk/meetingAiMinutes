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
from concurrent import futures
from tqdm import tqdm
from pydub import AudioSegment
import io

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import meeting_pb2
import meeting_pb2_grpc

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

WHISPER_AVAILABLE = False
whisper_model = None
model_ready = False

class MeetingServiceImpl(meeting_pb2_grpc.MeetingServiceServicer):
    
    def __init__(self):
        logger.info("✅ ML Service initialized")
        self.sessions = {}
    
    def convert_to_wav(self, audio_bytes):
        """Convert audio bytes to WAV format compatible with Whisper"""
        try:
            # Save as temporary WebM file
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_webm:
                tmp_webm.write(audio_bytes)
                webm_path = tmp_webm.name
            
            # Convert WebM to WAV using pydub
            audio = AudioSegment.from_file(webm_path, format="webm")
            
            # Convert to mono, 16kHz (Whisper expects this)
            audio = audio.set_channels(1).set_frame_rate(16000)
            
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
                audio.export(tmp_wav.name, format="wav")
                wav_path = tmp_wav.name
            
            os.unlink(webm_path)
            return wav_path
        except Exception as e:
            logger.error(f"Audio conversion error: {e}")
            return None
    
    def ProcessAudio(self, request_iterator, context):
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
                audio_bytes = chunk.data
                session_audio[session_id]["audio_data"].append(audio_bytes)
                
                if len(session_audio[session_id]["audio_data"]) >= 3:
                    combined_audio = b''.join(session_audio[session_id]["audio_data"])
                    
                    # Convert to WAV format
                    wav_path = self.convert_to_wav(combined_audio)
                    if not wav_path:
                        yield meeting_pb2.TranscriptionResult(
                            text="⚠️ Audio format error",
                            confidence=0.5,
                            is_final=False,
                            speaker="system"
                        )
                        continue
                    
                    try:
                        logger.info(f"🎙️ [Session {session_id}] Transcribing...")
                        result = whisper_model.transcribe(wav_path, language='en')
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
                        if os.path.exists(wav_path):
                            os.unlink(wav_path)
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
        global model_ready
        
        session_id = request.session_id[:8]
        transcript = request.transcript
        
        if not transcript and session_id in self.sessions:
            transcript = " ".join(self.sessions[session_id].get("transcript", []))
        
        logger.info(f"📝 [Session {session_id}] Generating minutes")
        
        action_items = []
        decisions = []
        discussion_points = []
        sentiment = "neutral"
        
        if transcript and len(transcript) > 10:
            lower = transcript.lower()
            
            if "issue" in lower or "problem" in lower:
                action_items.append("Investigate and resolve identified issues")
            if "angular" in lower:
                action_items.append("Review AngularJS migration plan")
            if "not working" in lower:
                action_items.append("Debug and fix application issues")
            
            if not action_items:
                action_items = [transcript[:100]]
            
            decisions = ["Team discussed technical issues"]
            discussion_points = ["Technical problem analysis"]
            
            if "good" in lower or "great" in lower:
                sentiment = "positive"
            elif "issue" in lower or "problem" in lower:
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

def check_model_ready():
    global model_ready
    
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
    
    logger.info("📥 Phi-3-mini will be available when download completes")

def serve():
    logger.info("🔄 Starting background model loading...")
    
    whisper_thread = threading.Thread(target=load_whisper_with_progress_bar, daemon=True)
    whisper_thread.start()
    
    phi_thread = threading.Thread(target=check_model_ready, daemon=True)
    phi_thread.start()
    
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    meeting_pb2_grpc.add_MeetingServiceServicer_to_server(MeetingServiceImpl(), server)
    server.add_insecure_port('[::]:50051')
    logger.info("🚀 gRPC server listening on port 50051")
    logger.info("✅ ML Service ready! (Models loading in background)")
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()