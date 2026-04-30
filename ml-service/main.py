#!/usr/bin/env python3
"""ML Service for meetingAiHackathon - Real‑time streaming with persistent FFmpeg + VAD"""

import grpc
import logging
import sys
import os
import tempfile
import threading
import time
import subprocess
import numpy as np
from concurrent import futures
from tqdm import tqdm
import wave
import struct
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import meeting_pb2
import meeting_pb2_grpc

# ----------------------------------------------------------------------
# Logging setup
# ----------------------------------------------------------------------
class TqdmLoggingHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            tqdm.write(msg)
        except Exception:
            self.handleError(record)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%H:%M:%S',
    handlers=[TqdmLoggingHandler()]
)
logger = logging.getLogger(__name__)

WHISPER_AVAILABLE = False
whisper_model = None

# ----------------------------------------------------------------------
# Persistent FFmpeg transcriber with VAD
# ----------------------------------------------------------------------
class StreamingTranscriber:
    def __init__(self, session_short_id: str, sample_rate=16000, chunk_seconds=3):
        self.session_id = session_short_id
        self.sample_rate = sample_rate
        # 3 seconds of 16-bit PCM = 16000 * 3 * 2 = 96000 bytes
        self.chunk_size = sample_rate * chunk_seconds * 2
        self.ffmpeg = None
        self.pcm_buffer = b""
        self.running = False
        self.lock = threading.Lock()
        self.reader_thread = None
        self.last_text = ""
        self.received_transcripts = []
        self.energy_threshold = 0.008   # RMS threshold for VAD (lower = more sensitive)

    def start(self):
        cmd = [
            'ffmpeg', '-loglevel', 'error',
            '-f', 'webm', '-i', 'pipe:0',
            '-f', 's16le', '-acodec', 'pcm_s16le',
            '-ar', str(self.sample_rate), '-ac', '1',
            'pipe:1'
        ]
        logger.info(f"🎙️ [{self.session_id}] Starting persistent FFmpeg")
        try:
            self.ffmpeg = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0
            )
            self.running = True
            self.reader_thread = threading.Thread(target=self._read_pcm, daemon=True)
            self.reader_thread.start()
            logger.info(f"✅ [{self.session_id}] Persistent FFmpeg running")
        except Exception as e:
            logger.error(f"❌ [{self.session_id}] Failed to start FFmpeg: {e}")
            self.ffmpeg = None
            self.running = False

    def feed_chunk(self, webm_data: bytes):
        if not self.running or not self.ffmpeg:
            return
        try:
            self.ffmpeg.stdin.write(webm_data)
            self.ffmpeg.stdin.flush()
        except BrokenPipeError:
            logger.warning(f"⚠️ [{self.session_id}] FFmpeg stdin broken, stopping")
            self.stop()
        except Exception as e:
            logger.error(f"❌ [{self.session_id}] FFmpeg stdin error: {e}")
            self.stop()

    def _read_pcm(self):
        while self.running and self.ffmpeg and self.ffmpeg.stdout:
            try:
                pcm_data = self.ffmpeg.stdout.read(16384)
                if not pcm_data:
                    break
                with self.lock:
                    self.pcm_buffer += pcm_data
            except Exception as e:
                logger.error(f"❌ [{self.session_id}] PCM read error: {e}")
                break
        logger.info(f"📭 [{self.session_id}] PCM reader thread stopped")

    def get_ready_chunks(self):
        chunks = []
        with self.lock:
            while len(self.pcm_buffer) >= self.chunk_size:
                chunk = self.pcm_buffer[:self.chunk_size]
                self.pcm_buffer = self.pcm_buffer[self.chunk_size:]
                chunks.append(chunk)
        return chunks

    def transcribe_chunk(self, pcm_chunk: bytes):
        if not WHISPER_AVAILABLE or whisper_model is None:
            return "", 0.0
        try:
            # Convert 16-bit PCM to float32
            audio = np.frombuffer(pcm_chunk, dtype=np.int16).astype(np.float32) / 32768.0
            
            # Voice activity detection – skip if too quiet
            rms = np.sqrt(np.mean(audio**2))
            if rms < self.energy_threshold:
                return "", 0.0
            
            # Transcribe with Whisper
            result = whisper_model.transcribe(audio, language='en', fp16=False)
            text = result['text'].strip()
            conf = result.get('confidence', 0.8)
            
            # Filter out very short or meaningless outputs
            if len(text) < 2 or text == '.' or text == '...' or text == '?':
                return "", 0.0
                
            return text, conf
        except Exception as e:
            logger.error(f"❌ [{self.session_id}] Transcription error: {e}")
            return "", 0.0

    def stop(self):
        self.running = False
        if self.ffmpeg:
            logger.info(f"🧹 [{self.session_id}] Stopping FFmpeg...")
            try:
                if self.ffmpeg.stdin:
                    self.ffmpeg.stdin.close()
                self.ffmpeg.terminate()
                self.ffmpeg.wait(timeout=3)
            except:
                self.ffmpeg.kill()
            self.ffmpeg = None
        logger.info(f"✅ [{self.session_id}] Transcriber cleaned up")

# ----------------------------------------------------------------------
# gRPC service implementation
# ----------------------------------------------------------------------
class MeetingServiceImpl(meeting_pb2_grpc.MeetingServiceServicer):
    def __init__(self):
        logger.info("=" * 60)
        logger.info("✅ ML Service initialized with persistent FFmpeg streaming (Whisper base.en)")
        logger.info("=" * 60)
        self.sessions = defaultdict(lambda: {"transcript": []})
        self.streamers = {}
        self.chunk_counter = 0
        self.lock = threading.Lock()

    def ProcessAudio(self, request_iterator, context):
        """Real‑time processing: feed WebM chunks to persistent FFmpeg, transcribe PCM slices."""
        stream_id = datetime.now().strftime("%H%M%S%f")
        logger.info(f"🔊 [Stream-{stream_id}] New gRPC stream opened (real‑time mode)")

        session_id = None
        transcriber = None

        try:
            for chunk in request_iterator:
                self.chunk_counter += 1
                session_id = chunk.session_id
                if not session_id:
                    logger.error("❌ Empty session_id in chunk")
                    continue

                short_id = session_id[-8:] if len(session_id) > 8 else session_id

                # Create a persistent transcriber for this session on first chunk
                with self.lock:
                    if session_id not in self.streamers:
                        transcriber = StreamingTranscriber(short_id)
                        transcriber.start()
                        self.streamers[session_id] = transcriber
                        logger.info(f"🆕 [Session {short_id}] Created persistent transcriber")

                    transcriber = self.streamers[session_id]

                # Feed the incoming WebM chunk to FFmpeg
                transcriber.feed_chunk(chunk.data)

                # Process any complete PCM chunks that have accumulated
                for pcm_chunk in transcriber.get_ready_chunks():
                    text, conf = transcriber.transcribe_chunk(pcm_chunk)
                    if text and len(text) > 1 and text != '.' and text != transcriber.last_text:
                        transcriber.last_text = text

                        # Store in global session transcript (for final minutes)
                        with self.lock:
                            self.sessions[session_id]["transcript"].append(text)
                        transcriber.received_transcripts.append(text)

                        logger.info(f"📝 [Session {short_id}] Real‑time transcription: '{text}' (total stored: {len(self.sessions[session_id]['transcript'])})")

                        # Send transcription back to client (non‑final)
                        yield meeting_pb2.TranscriptionResult(
                            text=text,
                            confidence=conf,
                            is_final=False,
                            speaker="participant"
                        )

        except Exception as e:
            logger.error(f"💥 [Stream-{stream_id}] Error: {e}", exc_info=True)
            raise
        finally:
            if session_id:
                with self.lock:
                    if session_id in self.streamers:
                        self.streamers[session_id].stop()
                        del self.streamers[session_id]
                logger.info(f"🔚 [Session {session_id[-8:] if session_id else '?'}] Transcriber stopped")
            logger.info(f"🔚 [Stream-{stream_id}] Closed. Total chunks: {self.chunk_counter}")

    def GenerateMinutes(self, request, context):
        """Generate minutes using Ollama Phi-3 for intelligent extraction"""
        session_id = request.session_id
        transcript = request.transcript

        short_id = session_id[-8:] if len(session_id) > 8 else session_id
        logger.info(f"📝 [Session {short_id}] GenerateMinutes called, input transcript length {len(transcript)}")

        # If caller didn't provide transcript, use stored one
        if not transcript:
            with self.lock:
                stored = self.sessions.get(session_id, {}).get("transcript", [])
                transcript = " ".join(stored)
                logger.info(f"📚 Retrieved stored transcript: {len(stored)} entries -> '{transcript[:100]}'")

        # If still empty, try to get from transcriber's cache (fallback)
        if not transcript:
            with self.lock:
                transcriber = self.streamers.get(session_id)
                if transcriber and transcriber.received_transcripts:
                    transcript = " ".join(transcriber.received_transcripts)
                    logger.info(f"🔄 Fallback: using transcriber cache ({len(transcriber.received_transcripts)} entries)")

        action_items = []
        decisions = []
        discussion_points = []
        sentiment = "neutral"

        # Use Ollama if we have substantial transcript
        if transcript and len(transcript) > 20:
            try:
                import requests
                import json
                import re
                
                OLLAMA_HOST = os.environ.get('OLLAMA_HOST', 'http://ollama:11434')
                
                # Check available models
                resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
                if resp.status_code == 200:
                    models = resp.json().get('models', [])
                    model_names = [m['name'] for m in models]
                    
                    # Use phi3 or any available model
                    model_name = None
                    for model in ['phi3:mini', 'tinyllama:latest', 'llama3.2:latest']:
                        if model in model_names or model.split(':')[0] in [m.split(':')[0] for m in model_names]:
                            model_name = model
                            break
                    
                    if not model_name and model_names:
                        model_name = model_names[0]
                    
                    if model_name:
                        logger.info(f"🤖 [Session {short_id}] Using Ollama model: {model_name}")
                        
                        prompt = f"""Meeting transcript: {transcript}

Extract exactly in this JSON format (use simple strings, no nested objects):
{{
    "action_items": ["task 1", "task 2"],
    "decisions": ["decision 1"],
    "discussion_points": ["point 1", "point 2"],
    "sentiment": "positive"
}}

Only output valid JSON, no other text."""

                        response = requests.post(
                            f"{OLLAMA_HOST}/api/generate",
                            json={
                                "model": model_name,
                                "prompt": prompt,
                                "stream": False,
                                "temperature": 0.2,
                                "num_predict": 300
                            },
                            timeout=60
                        )
                        
                        if response.status_code == 200:
                            result = response.json()
                            response_text = result.get('response', '')
                            logger.info(f"🤖 [Session {short_id}] Ollama response received in {response.elapsed.total_seconds():.1f}s")
                            
                            # Extract JSON from response
                            start_idx = response_text.find('{')
                            end_idx = response_text.rfind('}') + 1
                            if start_idx >= 0 and end_idx > start_idx:
                                json_str = response_text[start_idx:end_idx]
                                json_str = re.sub(r'```json\s*', '', json_str)
                                json_str = re.sub(r'```\s*', '', json_str)
                                json_str = re.sub(r',\s*}', '}', json_str)
                                json_str = re.sub(r',\s*]', ']', json_str)
                                
                                data = json.loads(json_str)
                                action_items = data.get('action_items', [])
                                decisions = data.get('decisions', [])
                                discussion_points = data.get('discussion_points', [])
                                sentiment = data.get('sentiment', 'neutral')
                                
                                logger.info(f"✅ [Session {short_id}] LLM extraction successful:")
                                logger.info(f"   Actions: {len(action_items)} - {action_items[:2] if action_items else []}")
                                logger.info(f"   Decisions: {len(decisions)} - {decisions[:2] if decisions else []}")
                                logger.info(f"   Sentiment: {sentiment}")
                            else:
                                logger.warning(f"⚠️ [Session {short_id}] No JSON found in response")
                        else:
                            logger.error(f"❌ [Session {short_id}] Ollama API error: {response.status_code}")
                else:
                    logger.warning(f"⚠️ [Session {short_id}] Cannot connect to Ollama: {resp.status_code}")
                    
            except requests.exceptions.Timeout:
                logger.warning(f"⚠️ [Session {short_id}] Ollama timeout")
            except requests.exceptions.ConnectionError:
                logger.error(f"❌ [Session {short_id}] Cannot connect to Ollama")
            except Exception as e:
                logger.error(f"❌ [Session {short_id}] LLM extraction error: {e}")

        # Intelligent fallback if LLM extraction failed
        if not action_items and transcript:
            logger.info(f"📝 [Session {short_id}] Using intelligent fallback extraction")
            
            # Extract action-like phrases
            import re
            action_patterns = [
                r'(?:need to|must|should|will|let\'s|lets)\s+([^.!?]+)',
                r'(?:schedule|arrange|prepare|create|review|check|update|fix|implement)\s+([^.!?]+)',
                r'(?:we need|we should|we must|we will)\s+([^.!?]+)',
            ]
            
            for pattern in action_patterns:
                matches = re.findall(pattern, transcript.lower())
                for match in matches[:2]:
                    action_text = match.strip().capitalize()
                    if len(action_text) > 5 and action_text not in action_items:
                        action_items.append(action_text)
            
            if not action_items:
                # Extract unique action items from transcript
                sentences = transcript.split('.')
                action_items = []
                for sentence in sentences[:3]:
                    sentence = sentence.strip()
                    if len(sentence) > 10 and sentence not in action_items:
                        action_items.append(sentence)
                else:
                    action_items = ["Review meeting transcript"]
            
            decisions = ["Continue with proposed plan"]
            discussion_points = [transcript[:150] if len(transcript) > 150 else transcript]
            sentiment = "positive" if any(w in transcript.lower() for w in ['good', 'great', 'agree', 'awesome', 'perfect']) else "neutral"
        
        # Ensure we have minimum content
        if not action_items:
            action_items = ["Review meeting transcript"]
        if not decisions:
            decisions = ["No formal decisions recorded"]
        if not discussion_points:
            discussion_points = ["Meeting held as scheduled"]
        
        # Limit results
        action_items = action_items[:5]
        decisions = decisions[:3]
        discussion_points = discussion_points[:5]
        
        logger.info(f"📤 [Session {short_id}] Final: {len(action_items)} actions, {len(decisions)} decisions")
        
        # Format action items as simple strings for the response
        formatted_actions = []
        for item in action_items:
            if isinstance(item, dict):
                formatted_actions.append(str(item.get('task', item.get('action', str(item)))))
            else:
                formatted_actions.append(str(item))
        
        return meeting_pb2.MinutesResponse(
            action_items=formatted_actions,
            decisions=[str(d) for d in decisions],
            discussion_points=[str(p) for p in discussion_points],
            sentiment=str(sentiment)
        )

# ----------------------------------------------------------------------
# Whisper model loading
# ----------------------------------------------------------------------
def load_whisper_with_progress_bar():
    global whisper_model, WHISPER_AVAILABLE
    
    logger.info("🎤 Starting Whisper model loading...")
    
    try:
        import whisper
        
        with tqdm(total=100, desc="🎤 Loading Whisper base.en (244M)", 
                  bar_format="{desc}: |{bar}| {percentage:3.0f}%",
                  colour="green") as pbar:
            
            pbar.update(10)
            whisper_model = whisper.load_model("base.en")
            pbar.update(90)
            
        WHISPER_AVAILABLE = True
        logger.info("=" * 60)
        logger.info("✅ Whisper base.en (244M) loaded successfully!")
        logger.info("=" * 60)
        
        # Test the model with a short silent audio to verify it works
        test_audio = np.zeros(16000, dtype=np.float32)
        test_result = whisper_model.transcribe(test_audio, fp16=False)
        logger.info(f"🧪 Whisper test successful")
        
    except Exception as e:
        logger.error(f"❌ Whisper loading failed: {e}", exc_info=True)
        WHISPER_AVAILABLE = False

def serve():
    logger.info("=" * 60)
    logger.info("🚀 meetingAiHackathon ML Service Starting (Persistent FFmpeg Streaming + Whisper base.en)")
    logger.info("=" * 60)
    
    logger.info("🔄 Starting background model loading...")
    whisper_thread = threading.Thread(target=load_whisper_with_progress_bar, daemon=True)
    whisper_thread.start()
    
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    meeting_pb2_grpc.add_MeetingServiceServicer_to_server(MeetingServiceImpl(), server)
    server.add_insecure_port('[::]:50051')
    
    logger.info("🚀 gRPC server listening on port 50051")
    logger.info("✅ ML Service ready for real‑time streaming!")
    logger.info("=" * 60)
    
    server.start()
    
    # Heartbeat
    def log_status():
        while True:
            time.sleep(30)
            logger.info(f"💓 Heartbeat - Whisper ready: {WHISPER_AVAILABLE}")
    
    status_thread = threading.Thread(target=log_status, daemon=True)
    status_thread.start()
    
    server.wait_for_termination()

if __name__ == '__main__':
    serve()