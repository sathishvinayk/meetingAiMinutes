#!/usr/bin/env python3
"""ML Service for MeetingPulse - Fixed Audio Processing with FFmpeg"""

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
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%H:%M:%S',
    handlers=[TqdmLoggingHandler()]
)
logger = logging.getLogger(__name__)

WHISPER_AVAILABLE = False
whisper_model = None

def convert_webm_to_wav_with_ffmpeg(webm_data):
    """Convert WebM to WAV with proper preprocessing for Whisper"""
    try:
        # Write WebM data to temp file
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as webm_file:
            webm_file.write(webm_data)
            webm_path = webm_file.name
        
        # Create WAV temp file
        wav_path = tempfile.mktemp(suffix=".wav")
        
        # Convert using ffmpeg with optimal settings for speech recognition
        cmd = [
            'ffmpeg', '-i', webm_path,
            '-acodec', 'pcm_s16le',     # 16-bit PCM
            '-ar', '16000',              # 16kHz sample rate (Whisper expects this)
            '-ac', '1',                  # Mono
            '-af', 'volume=2.0,highpass=f=200,lowpass=f=3000',  # Amplify and filter for speech
            '-y', wav_path
        ]
        
        logger.info(f"🎵 Running FFmpeg conversion: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode != 0:
            logger.error(f"❌ FFmpeg conversion failed: {result.stderr}")
            return None
        
        # Read the converted WAV file
        with open(wav_path, 'rb') as wav_file:
            wav_data = wav_file.read()
        
        # Verify WAV file is valid
        if len(wav_data) < 44:
            logger.error(f"❌ WAV file too small: {len(wav_data)} bytes")
            return None
        
        # Get audio duration
        with wave.open(wav_path, 'rb') as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
            duration = frames / float(rate)
            logger.info(f"✅ Converted audio: {duration:.2f} seconds, {rate}Hz, {wav.getnchannels()} channel(s)")
            
            if duration < 0.5:
                logger.warning(f"⚠️ Audio too short: {duration:.2f} seconds")
        
        # Cleanup temp files
        os.unlink(webm_path)
        
        return wav_path
        
    except subprocess.TimeoutExpired:
        logger.error("❌ FFmpeg conversion timeout")
        return None
    except Exception as e:
        logger.error(f"❌ Conversion error: {e}", exc_info=True)
        return None

def preprocess_audio_for_whisper(wav_path):
    """Additional preprocessing to improve transcription"""
    try:
        # Read the WAV file
        with wave.open(wav_path, 'rb') as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
            duration = frames / float(rate)
            
            # Check if audio is too short
            if duration < 0.5:
                logger.warning(f"⚠️ Audio too short ({duration:.2f}s), skipping")
                return None
            
            # Read audio data as numpy array
            audio_data = np.frombuffer(wav.readframes(frames), dtype=np.int16)
            
            # Check audio level
            max_amplitude = np.max(np.abs(audio_data))
            logger.info(f"📊 Audio stats: max amplitude={max_amplitude}, mean={np.mean(np.abs(audio_data)):.0f}")
            
            if max_amplitude < 100:
                logger.warning(f"⚠️ Audio too quiet (max amplitude={max_amplitude})")
                # Amplify quiet audio
                amplification_factor = min(5.0, 30000 / max(max_amplitude, 1))
                audio_data = (audio_data * amplification_factor).astype(np.int16)
                logger.info(f"🔊 Amplified audio by {amplification_factor:.1f}x")
                
                # Save amplified version
                amplified_path = tempfile.mktemp(suffix=".wav")
                with wave.open(amplified_path, 'wb') as amplified_wav:
                    amplified_wav.setnchannels(1)
                    amplified_wav.setsampwidth(2)
                    amplified_wav.setframerate(rate)
                    amplified_wav.writeframes(audio_data.tobytes())
                return amplified_path
        
        return wav_path
        
    except Exception as e:
        logger.error(f"❌ Preprocessing error: {e}", exc_info=True)
        return wav_path

class MeetingServiceImpl(meeting_pb2_grpc.MeetingServiceServicer):
    
    def __init__(self):
        logger.info("=" * 60)
        logger.info("✅ ML Service initialized")
        logger.info("=" * 60)
        self.sessions = {}
        self.chunk_counter = 0
    
    def ProcessAudio(self, request_iterator, context):
        """Process streaming audio chunks with detailed logging"""
        
        stream_id = datetime.now().strftime("%H%M%S%f")
        logger.info(f"🔊 [Stream-{stream_id}] New gRPC stream opened")
        
        session_audio = {}
        
        try:
            for chunk in request_iterator:
                self.chunk_counter += 1
                session_id = chunk.session_id
                
                if not session_id:
                    logger.error(f"❌ Empty session_id in chunk {chunk.sequence}")
                    continue
                
                short_id = session_id[-8:] if len(session_id) > 8 else session_id
                
                # Initialize session storage
                if session_id not in session_audio:
                    session_audio[session_id] = {
                        "audio_data": None,
                        "last_text": "",
                        "chunks": 0,
                        "processed": False
                    }
                    logger.info(f"🆕 [Session {short_id}] New audio session initialized")
                
                session_audio[session_id]["chunks"] += 1
                
                # Store the complete audio data (assuming it comes in one chunk now)
                if not session_audio[session_id]["processed"]:
                    session_audio[session_id]["audio_data"] = chunk.data
                    logger.info(f"📦 [Session {short_id}] Received audio: {len(chunk.data)} bytes")
                    
                    # Check Whisper availability
                    if not WHISPER_AVAILABLE or whisper_model is None:
                        logger.warning(f"⚠️ [Session {short_id}] Whisper not ready yet")
                        yield meeting_pb2.TranscriptionResult(
                            text="⏳ Loading Whisper model...",
                            confidence=0.5,
                            is_final=False,
                            speaker="system"
                        )
                        continue
                    
                    # Process the audio
                    logger.info(f"🎙️ [Session {short_id}] Processing {len(chunk.data)} bytes of audio")
                    
                    # Convert WebM to WAV with preprocessing
                    wav_path = convert_webm_to_wav_with_ffmpeg(chunk.data)
                    
                    if wav_path and os.path.exists(wav_path):
                        try:
                            # Additional preprocessing
                            processed_wav = preprocess_audio_for_whisper(wav_path)
                            
                            if processed_wav and os.path.exists(processed_wav):
                                logger.info(f"🤖 [Session {short_id}] Starting Whisper transcription...")
                                
                                # Transcribe with Whisper
                                result = whisper_model.transcribe(
                                    processed_wav, 
                                    language='en',
                                    task='transcribe',
                                    fp16=False  # CPU fallback
                                )
                                
                                text = result['text'].strip()
                                logger.info(f"📝 [Session {short_id}] Whisper output: '{text}' (length: {len(text)})")
                                
                                if text and text != '.' and len(text) > 1:
                                    session_audio[session_id]["last_text"] = text
                                    session_audio[session_id]["processed"] = True
                                    
                                    # Store in global sessions
                                    if session_id not in self.sessions:
                                        self.sessions[session_id] = {"transcript": []}
                                    
                                    self.sessions[session_id]["transcript"].append(text)
                                    
                                    logger.info(f"✅ [Session {short_id}] Successfully transcribed: '{text[:100]}'")
                                    
                                    # Send the result
                                    yield meeting_pb2.TranscriptionResult(
                                        text=text,
                                        confidence=result.get('confidence', 0.9),
                                        is_final=True,
                                        speaker="participant"
                                    )
                                else:
                                    logger.warning(f"⚠️ [Session {short_id}] No speech detected or transcription too short")
                                    yield meeting_pb2.TranscriptionResult(
                                        text="No speech detected. Please speak louder and clearer.",
                                        confidence=0.3,
                                        is_final=True,
                                        speaker="system"
                                    )
                            else:
                                logger.error(f"❌ [Session {short_id}] Failed to preprocess audio")
                                
                        except Exception as e:
                            logger.error(f"❌ [Session {short_id}] Transcription error: {e}", exc_info=True)
                            yield meeting_pb2.TranscriptionResult(
                                text=f"Transcription error: {str(e)[:50]}",
                                confidence=0.0,
                                is_final=True,
                                speaker="system"
                            )
                        finally:
                            # Cleanup temp files
                            if wav_path and os.path.exists(wav_path):
                                os.unlink(wav_path)
                            if processed_wav != wav_path and processed_wav and os.path.exists(processed_wav):
                                os.unlink(processed_wav)
                    else:
                        logger.error(f"❌ [Session {short_id}] Failed to convert audio")
                        yield meeting_pb2.TranscriptionResult(
                            text="Audio conversion failed",
                            confidence=0.0,
                            is_final=True,
                            speaker="system"
                        )
                
        except Exception as e:
            logger.error(f"💥 [Stream-{stream_id}] Fatal stream error: {e}", exc_info=True)
            raise
        
        finally:
            logger.info(f"🔚 [Stream-{stream_id}] Stream closed")

    def GenerateMinutes(self, request, context):
        """Generate minutes using Ollama Phi-3 for intelligent extraction"""
        session_id = request.session_id
        transcript = request.transcript
        
        short_id = session_id[-8:] if len(session_id) > 8 else session_id
        
        logger.info(f"📝 [Session {short_id}] GenerateMinutes called with transcript length {len(transcript)}")
        
        if not transcript and session_id in self.sessions:
            stored = self.sessions[session_id].get("transcript", [])
            transcript = " ".join(stored)
            logger.info(f"📚 Using stored transcript: {len(stored)} entries, text: '{transcript[:200]}'")
        
        action_items = []
        decisions = []
        discussion_points = []
        sentiment = "neutral"
        
        # Use Ollama Phi-3 for intelligent extraction
        if transcript and len(transcript) > 20:
            try:
                import requests
                import json
                import re
                
                OLLAMA_HOST = os.environ.get('OLLAMA_HOST', 'http://ollama:11434')
                
                # Check available models
                response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
                if response.status_code == 200:
                    models = response.json().get('models', [])
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
                        
                        # Simplified prompt that forces simple string arrays
                        prompt = f"""Meeting transcript: {transcript}

    Extract exactly in this JSON format (use simple strings, no nested objects):
    {{
        "action_items": ["task 1", "task 2"],
        "decisions": ["decision 1"],
        "discussion_points": ["point 1", "point 2"],
        "sentiment": "positive"
    }}

    Only output valid JSON, no other text."""

                        # Call Ollama API with shorter timeout
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
                            
                            # Try multiple JSON extraction strategies
                            json_str = None
                            
                            # Strategy 1: Find JSON between curly braces
                            start_idx = response_text.find('{')
                            end_idx = response_text.rfind('}') + 1
                            if start_idx >= 0 and end_idx > start_idx:
                                json_str = response_text[start_idx:end_idx]
                            
                            # Strategy 2: Clean up markdown code blocks
                            if json_str:
                                json_str = re.sub(r'```json\s*', '', json_str)
                                json_str = re.sub(r'```\s*', '', json_str)
                                
                                # Fix common JSON issues
                                json_str = re.sub(r',\s*}', '}', json_str)
                                json_str = re.sub(r',\s*]', ']', json_str)
                                
                                try:
                                    data = json.loads(json_str)
                                    
                                    # Extract and flatten action_items if they're objects
                                    raw_actions = data.get('action_items', [])
                                    action_items = []
                                    for item in raw_actions:
                                        if isinstance(item, dict):
                                            task = item.get('task') or item.get('action') or item.get('description') or str(item)
                                            if task and task not in action_items:
                                                action_items.append(task)
                                        elif isinstance(item, str) and item:
                                            action_items.append(item)
                                    
                                    # Extract decisions
                                    decisions = data.get('decisions', [])
                                    if isinstance(decisions, list):
                                        decisions = [d for d in decisions if isinstance(d, str) and d]
                                    
                                    # Extract discussion points
                                    discussion_points = data.get('discussion_points', [])
                                    if isinstance(discussion_points, list):
                                        discussion_points = [p for p in discussion_points if isinstance(p, str) and p]
                                    
                                    sentiment = data.get('sentiment', 'neutral')
                                    
                                    logger.info(f"✅ [Session {short_id}] LLM extraction successful:")
                                    logger.info(f"   Actions: {len(action_items)} - {action_items[:2] if action_items else []}")
                                    logger.info(f"   Decisions: {len(decisions)} - {decisions[:2] if decisions else []}")
                                    logger.info(f"   Sentiment: {sentiment}")
                                    
                                except json.JSONDecodeError as e:
                                    logger.error(f"❌ [Session {short_id}] JSON parse error: {e}")
                                    logger.error(f"   Attempted to parse: {json_str[:200]}")
                                    
                                    # Try to extract simple strings using regex as fallback
                                    action_matches = re.findall(r'"task"?:\s*"([^"]+)"', response_text)
                                    if action_matches:
                                        action_items = action_matches[:3]
                                        logger.info(f"📌 Extracted actions via regex: {action_items}")
                        else:
                            logger.error(f"❌ [Session {short_id}] Ollama API error: {response.status_code}")
                else:
                    logger.warning(f"⚠️ [Session {short_id}] Cannot connect to Ollama: {response.status_code}")
                    
            except requests.exceptions.Timeout:
                logger.warning(f"⚠️ [Session {short_id}] Ollama timeout")
            except requests.exceptions.ConnectionError:
                logger.error(f"❌ [Session {short_id}] Cannot connect to Ollama")
            except Exception as e:
                logger.error(f"❌ [Session {short_id}] LLM error: {e}")
        
        # Intelligent fallback if LLM extraction failed
        if not action_items and transcript:
            logger.info(f"📝 [Session {short_id}] Using intelligent fallback extraction")
            
            # Extract action-like phrases
            import re
            action_patterns = [
                r'(?:need to|must|should|will|let\'s|lets)\s+([^.!?]+)',
                r'(?:schedule|arrange|prepare|create|review|check|update|fix|implement)\s+([^.!?]+)',
            ]
            
            for pattern in action_patterns:
                matches = re.findall(pattern, transcript.lower())
                for match in matches[:2]:
                    action_text = match.strip().capitalize()
                    if len(action_text) > 5 and action_text not in action_items:
                        action_items.append(action_text)
            
            if not action_items:
                # Use first sentence as action
                first_sentence = transcript.split('.')[0].strip()
                if len(first_sentence) > 10:
                    action_items = [f"Discuss: {first_sentence[:80]}"]
            
            decisions = ["Continue with proposed plan"]
            discussion_points = [transcript[:150]]
            sentiment = "positive" if any(w in transcript.lower() for w in ['good', 'great', 'agree']) else "neutral"
        
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
    
    # def GenerateMinutes(self, request, context):
    #     """Generate minutes using Ollama Phi-3 for intelligent extraction"""
    #     session_id = request.session_id
    #     transcript = request.transcript
        
    #     short_id = session_id[-8:] if len(session_id) > 8 else session_id
        
    #     logger.info(f"📝 [Session {short_id}] GenerateMinutes called with transcript length {len(transcript)}")
        
    #     if not transcript and session_id in self.sessions:
    #         stored = self.sessions[session_id].get("transcript", [])
    #         transcript = " ".join(stored)
    #         logger.info(f"📚 Using stored transcript: {len(stored)} entries, text: '{transcript[:200]}'")
        
    #     action_items = []
    #     decisions = []
    #     discussion_points = []
    #     sentiment = "neutral"
        
    #     # Use Ollama Phi-3 for intelligent extraction
    #     if transcript and len(transcript) > 20:
    #         try:
    #             import requests
    #             import json
                
    #             OLLAMA_HOST = os.environ.get('OLLAMA_HOST', 'http://ollama:11434')
                
    #             # Check if phi3 model is available
    #             response = requests.get(f"{OLLAMA_HOST}/api/tags")
    #             if response.status_code == 200:
    #                 models = response.json().get('models', [])
    #                 model_names = [m['name'] for m in models]
                    
    #                 # Use phi3 if available, otherwise fallback to any available model
    #                 model_name = None
    #                 for model in ['phi3:mini', 'phi3:3.8b-mini-4k-instruct', 'phi3:latest', 'llama3.2:latest', 'mistral:latest']:
    #                     if model in model_names or model.split(':')[0] in [m.split(':')[0] for m in model_names]:
    #                         model_name = model
    #                         break
                    
    #                 if not model_name and model_names:
    #                     model_name = model_names[0]  # Use first available model
                    
    #                 if model_name:
    #                     logger.info(f"🤖 [Session {short_id}] Using Ollama model: {model_name}")
                        
    #                     prompt = f"""You are a meeting assistant. Analyze this meeting transcript and extract key information.

    # Transcript: {transcript}

    # Extract the following in JSON format:
    # 1. action_items: What specific tasks or actions need to be done? Who needs to do what? Be specific.
    # 2. decisions: What decisions were made during the meeting?
    # 3. discussion_points: Main topics discussed (3-5 key points)
    # 4. sentiment: Overall meeting sentiment (positive/neutral/negative)

    # Example output format:
    # {{
    #     "action_items": ["Schedule follow-up meeting by Friday", "John to update documentation", "Review code changes"],
    #     "decisions": ["Use React for frontend", "Deploy next Tuesday"],
    #     "discussion_points": ["Project timeline discussion", "Resource allocation", "Technical challenges"],
    #     "sentiment": "positive"
    # }}

    # Return ONLY valid JSON, no other text."""

    #                     # Call Ollama API
    #                     response = requests.post(
    #                         f"{OLLAMA_HOST}/api/generate",
    #                         json={
    #                             "model": model_name,
    #                             "prompt": prompt,
    #                             "stream": False,
    #                             "temperature": 0.3,
    #                             "top_p": 0.9,
    #                             "top_k": 40,

    #                         },
    #                         timeout=120
    #                     )
                        
    #                     if response.status_code == 200:
    #                         result = response.json()
    #                         response_text = result.get('response', '')
    #                         logger.info(f"🤖 [Session {short_id}] Ollama response received: {response_text[:200]}")
                            
    #                         # Extract JSON from response
    #                         try:
    #                             # Find JSON in the response (between { and })
    #                             start_idx = response_text.find('{')
    #                             end_idx = response_text.rfind('}') + 1
    #                             if start_idx >= 0 and end_idx > start_idx:
    #                                 json_str = response_text[start_idx:end_idx]
    #                                 data = json.loads(json_str)
                                    
    #                                 action_items = data.get('action_items', [])
    #                                 decisions = data.get('decisions', [])
    #                                 discussion_points = data.get('discussion_points', [])
    #                                 sentiment = data.get('sentiment', 'neutral')
                                    
    #                                 logger.info(f"✅ [Session {short_id}] LLM extraction successful:")
    #                                 logger.info(f"   Actions: {len(action_items)} - {action_items[:2]}")
    #                                 logger.info(f"   Decisions: {len(decisions)} - {decisions[:2]}")
    #                                 logger.info(f"   Sentiment: {sentiment}")
    #                             else:
    #                                 logger.warning(f"⚠️ [Session {short_id}] No JSON found in response")
    #                         except json.JSONDecodeError as e:
    #                             logger.error(f"❌ [Session {short_id}] Failed to parse JSON: {e}")
    #                             logger.error(f"   Response text: {response_text[:500]}")
    #                     else:
    #                         logger.error(f"❌ [Session {short_id}] Ollama API error: {response.status_code}")
    #                 else:
    #                     logger.warning(f"⚠️ [Session {short_id}] No suitable model found in Ollama")
    #             else:
    #                 logger.warning(f"⚠️ [Session {short_id}] Cannot connect to Ollama: {response.status_code}")
                    
    #         except requests.exceptions.Timeout:
    #             logger.error(f"❌ [Session {short_id}] Ollama request timeout")
    #         except requests.exceptions.ConnectionError:
    #             logger.error(f"❌ [Session {short_id}] Cannot connect to Ollama at {OLLAMA_HOST}")
    #         except Exception as e:
    #             logger.error(f"❌ [Session {short_id}] LLM extraction error: {e}", exc_info=True)
        
    #     # Fallback if LLM extraction failed or returned empty
    #     if not action_items:
    #         logger.warning(f"⚠️ [Session {short_id}] Using fallback extraction")
    #         if transcript and len(transcript) > 10:
    #             # Simple fallback: use transcript sentences
    #             sentences = transcript.split('.')
    #             for sentence in sentences[:3]:
    #                 if len(sentence.strip()) > 10:
    #                     action_items.append(f"Follow up: {sentence.strip()[:80]}")
    #             decisions = ["Review meeting notes"]
    #             discussion_points = [transcript[:200]]
    #             sentiment = "neutral"
    #         else:
    #             action_items = ["No action items extracted"]
    #             decisions = ["No decisions recorded"]
    #             discussion_points = ["No discussion points recorded"]
    #             sentiment = "neutral"
        
    #     # Ensure we don't exceed limits
    #     action_items = action_items[:5]
    #     decisions = decisions[:3]
    #     discussion_points = discussion_points[:5]
        
    #     logger.info(f"📤 [Session {short_id}] Final minutes: {len(action_items)} actions, {len(decisions)} decisions")
        
    #     return meeting_pb2.MinutesResponse(
    #         action_items=action_items,
    #         decisions=decisions,
    #         discussion_points=discussion_points,
    #         sentiment=sentiment
    #     )

def load_whisper_with_progress_bar():
    global whisper_model, WHISPER_AVAILABLE
    
    logger.info("🎤 Starting Whisper model loading...")
    
    try:
        import whisper
        
        with tqdm(total=100, desc="🎤 Loading Whisper Tiny (74M)", 
                  bar_format="{desc}: |{bar}| {percentage:3.0f}%",
                  colour="green") as pbar:
            
            pbar.update(10)
            whisper_model = whisper.load_model("tiny.en")
            pbar.update(90)
            
        WHISPER_AVAILABLE = True
        logger.info("=" * 60)
        logger.info("✅ Whisper Tiny (74M) loaded successfully!")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"❌ Whisper loading failed: {e}", exc_info=True)

def serve():
    from datetime import datetime
    
    logger.info("=" * 60)
    logger.info("🚀 MeetingPulse ML Service Starting")
    logger.info("=" * 60)
    
    logger.info("🔄 Starting background model loading...")
    whisper_thread = threading.Thread(target=load_whisper_with_progress_bar, daemon=True)
    whisper_thread.start()
    
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    meeting_pb2_grpc.add_MeetingServiceServicer_to_server(MeetingServiceImpl(), server)
    server.add_insecure_port('[::]:50051')
    
    logger.info("🚀 gRPC server listening on port 50051")
    logger.info("✅ ML Service ready!")
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