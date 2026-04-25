#!/usr/bin/env python3
"""ML Service for MeetingPulse - Real Whisper Transcription"""

import grpc
import logging
import sys
import os
import json
import base64
import tempfile
import requests
import time
from concurrent import futures

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import meeting_pb2
import meeting_pb2_grpc

# Detailed logging format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

OLLAMA_HOST = os.environ.get('OLLAMA_HOST', 'http://ollama:11434')
logger.info(f"📡 Connected to Ollama at {OLLAMA_HOST}")

# Initialize Whisper
WHISPER_AVAILABLE = False
whisper_model = None

try:
    import numpy as np
    logger.info(f"✅ NumPy version: {np.__version__}")
    
    import whisper
    logger.info("🎤 Loading Whisper Tiny (74M) model...")
    whisper_model = whisper.load_model("tiny.en")
    WHISPER_AVAILABLE = True
    logger.info("✅ Whisper Tiny (74M) loaded successfully")
except ImportError as e:
    logger.error(f"❌ Import error: {e}")
except Exception as e:
    logger.error(f"❌ Whisper loading failed: {e}")

class MeetingServiceImpl(meeting_pb2_grpc.MeetingServiceServicer):
    
    def __init__(self):
        logger.info("✅ ML Service initialized")
        self.sessions = {}
    
    def ProcessAudio(self, request_iterator, context):
        """Process streaming audio with REAL Whisper transcription"""
        session_audio = {}
        
        for chunk in request_iterator:
            session_id = chunk.session_id[:8]
            logger.info(f"🎤 [Session {session_id}] Received audio chunk {chunk.sequence} (size: {len(chunk.data)} bytes)")
            
            if session_id not in session_audio:
                session_audio[session_id] = {"audio_data": [], "last_text": "", "chunks": 0}
                logger.info(f"📝 [Session {session_id}] New audio stream started")
            
            session_audio[session_id]["chunks"] += 1
            
            try:
                # Audio is already bytes, no need to decode
                audio_bytes = chunk.data
                session_audio[session_id]["audio_data"].append(audio_bytes)
                
                # Process every 4 chunks (approx 4 seconds of audio)
                if len(session_audio[session_id]["audio_data"]) >= 4 and WHISPER_AVAILABLE:
                    combined_audio = b''.join(session_audio[session_id]["audio_data"])
                    
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                        tmp.write(combined_audio)
                        tmp_path = tmp.name
                    
                    try:
                        logger.info(f"🎙️ [Session {session_id}] Transcribing {len(combined_audio)} bytes...")
                        result = whisper_model.transcribe(tmp_path, language='en')
                        text = result['text'].strip()
                        logger.info(f"📝 [Session {session_id}] Raw transcription: '{text}'")
                        
                        if text and text != session_audio[session_id]["last_text"]:
                            session_audio[session_id]["last_text"] = text
                            session_audio[session_id]["audio_data"] = []
                            
                            if session_id not in self.sessions:
                                self.sessions[session_id] = {"transcript": []}
                            self.sessions[session_id]["transcript"].append(text)
                            logger.info(f"✅ [Session {session_id}] Transcription stored: {text[:100]}")
                            
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
                    # Send interim result
                    if session_audio[session_id]["chunks"] % 2 == 0:
                        logger.info(f"⏳ [Session {session_id}] Waiting for more audio (have {len(session_audio[session_id]['audio_data'])} chunks, need 4)")
                        yield meeting_pb2.TranscriptionResult(
                            text="🎤 Listening...",
                            confidence=0.5,
                            is_final=False,
                            speaker="system"
                        )
            except Exception as e:
                logger.error(f"❌ [Session {session_id}] Audio processing error: {e}")
    
    def GenerateMinutes(self, request, context):
        """Generate minutes using Phi-3 via Ollama"""
        session_id = request.session_id[:8]
        transcript = request.transcript
        logger.info(f"📝 [Session {session_id}] GenerateMinutes called")
        logger.info(f"📄 [Session {session_id}] Transcript length: {len(transcript)} chars")
        
        if not transcript and session_id in self.sessions:
            transcript = " ".join(self.sessions[session_id].get("transcript", []))
            logger.info(f"📚 [Session {session_id}] Using stored transcript: {len(transcript)} chars")
        
        action_items = []
        decisions = []
        discussion_points = []
        sentiment = "neutral"
        
        if transcript and len(transcript) > 20:
            logger.info(f"🤖 [Session {session_id}] Calling Phi-3 for analysis...")
            try:
                prompt = f"""Analyze this meeting transcript. Return ONLY valid JSON.

Transcript: {transcript[:1000]}

Return JSON in this format:
{{
    "action_items": ["person: action"],
    "decisions": ["decision"],
    "discussion_points": ["point"],
    "sentiment": "positive/neutral/negative"
}}"""

                response = requests.post(
                    f"{OLLAMA_HOST}/api/generate",
                    json={
                        "model": "phi3:mini",
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.3, "num_predict": 400}
                    },
                    timeout=60
                )
                
                if response.status_code == 200:
                    data = response.json()
                    text = data.get('response', '')
                    logger.info(f"🤖 [Session {session_id}] Phi-3 response: {text[:200]}")
                    
                    start = text.find('{')
                    end = text.rfind('}') + 1
                    if start >= 0 and end > start:
                        result = json.loads(text[start:end+1])
                        action_items = result.get('action_items', [])
                        decisions = result.get('decisions', [])
                        discussion_points = result.get('discussion_points', [])
                        sentiment = result.get('sentiment', 'neutral')
                        logger.info(f"✅ [Session {session_id}] Extracted {len(action_items)} action items")
            except Exception as e:
                logger.error(f"❌ [Session {session_id}] Ollama error: {e}")
        
        if not action_items:
            if transcript:
                action_items = [transcript[:100]]
            else:
                action_items = ["Speak for at least 4 seconds to generate action items"]
            decisions = ["No decisions recorded"]
            discussion_points = ["No discussion points recorded"]
        
        return meeting_pb2.MinutesResponse(
            action_items=action_items[:5],
            decisions=decisions[:3],
            discussion_points=discussion_points[:5],
            sentiment=sentiment
        )

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    meeting_pb2_grpc.add_MeetingServiceServicer_to_server(MeetingServiceImpl(), server)
    server.add_insecure_port('[::]:50051')
    logger.info("🚀 gRPC server on port 50051")
    logger.info(f"🎤 Whisper available: {WHISPER_AVAILABLE}")
    logger.info("✅ ML Service ready!")
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()