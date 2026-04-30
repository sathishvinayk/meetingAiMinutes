import React, { useState, useEffect, useRef, useCallback } from 'react';
import './App.css';

function App() {
  const [isRecording, setIsRecording] = useState(false);
  const [transcript, setTranscript] = useState([]);
  const [actionItems, setActionItems] = useState([]);
  const [decisions, setDecisions] = useState([]);
  const [discussionPoints, setDiscussionPoints] = useState([]);
  const [sentiment, setSentiment] = useState('neutral');
  const [sessionId, setSessionId] = useState(null);
  const [ws, setWs] = useState(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [micError, setMicError] = useState(null);
  const [volume, setVolume] = useState(0);
  const mediaRecorderRef = useRef(null);
  const streamRef = useRef(null);
  const recordingStartTimeRef = useRef(null);
  const chunkNumberRef = useRef(0);
  const isRecordingRef = useRef(false);
  const volumeIntervalRef = useRef(null);

  const addTranscriptMessage = useCallback((speaker, text) => {
    setTranscript(prev => [...prev, {
      id: Date.now(),
      speaker: speaker,
      text: text,
      timestamp: new Date().toLocaleTimeString()
    }]);
  }, []);

  const connectWebSocket = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const websocket = new WebSocket(`${protocol}//localhost:8080/ws`);
    
    websocket.onopen = () => {
      console.log('✅ WebSocket connected, waiting for session_id...');
      setIsConnected(true);
      setMicError(null);
    };
    
    websocket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        console.log('📨 Received message:', data.type);
        
        switch (data.type) {
          case 'session_init':
            const newSessionId = data.session_id;
            setSessionId(newSessionId);
            console.log('🎯 Session initialized with ID:', newSessionId);
            addTranscriptMessage('system', `✅ Ready! Session: ${newSessionId.slice(-8)}`);
            break;
            
          case 'transcription':
            console.log('📝 Transcription:', data.text);
            addTranscriptMessage(data.speaker || 'speaker', data.text);
            break;
            
          case 'minutes':
            if (data.payload) {
              console.log('📊 Minutes received:', data.payload);
              setActionItems(data.payload.action_items || []);
              setDecisions(data.payload.decisions || []);
              setDiscussionPoints(data.payload.discussion_points || []);
              setSentiment(data.payload.sentiment || 'neutral');
              setIsGenerating(false);
              addTranscriptMessage('system', '✅ Meeting minutes generated!');
            }
            break;
            
          default:
            console.log('Unknown message type:', data.type);
        }
      } catch (error) {
        console.error('Parse error:', error);
      }
    };
    
    websocket.onerror = (error) => {
      console.error('WebSocket error:', error);
      setIsConnected(false);
    };
    
    websocket.onclose = (event) => {
      console.log('WebSocket disconnected:', event.code, event.reason);
      setIsConnected(false);
      setTimeout(() => connectWebSocket(), 3000);
    };
    
    setWs(websocket);
    return websocket;
  }, [addTranscriptMessage]);

  useEffect(() => {
    const socket = connectWebSocket();
    return () => {
      if (socket) socket.close();
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop());
      }
      if (volumeIntervalRef.current) {
        clearInterval(volumeIntervalRef.current);
      }
    };
  }, [connectWebSocket]);

  const startRecording = async () => {
    setMicError(null);
    chunkNumberRef.current = 0;
    
    console.log('🎤 startRecording called, sessionId:', sessionId);
    console.log('WebSocket state:', ws?.readyState);
    
    if (!sessionId) {
      console.error('❌ No session ID! Wait for WebSocket connection.');
      addTranscriptMessage('system', '❌ Waiting for connection... Please try again.');
      return;
    }
    
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: true,
          channelCount: 1,
          sampleRate: 16000
        }
      });
      
      console.log('✅ Microphone stream obtained');
      streamRef.current = stream;
      
      // Setup volume meter
      const audioContext = new AudioContext();
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      const dataArray = new Uint8Array(analyser.frequencyBinCount);
      
      if (volumeIntervalRef.current) clearInterval(volumeIntervalRef.current);
      volumeIntervalRef.current = setInterval(() => {
        analyser.getByteTimeDomainData(dataArray);
        let max = 0;
        for (let i = 0; i < dataArray.length; i++) {
          const v = (dataArray[i] - 128) / 128;
          max = Math.max(max, Math.abs(v));
        }
        setVolume(max);
      }, 100);
      
      // Check available MIME types
      const mimeTypes = ['audio/webm', 'audio/webm;codecs=opus', 'audio/mp4', 'audio/mpeg'];
      let mimeType = '';
      for (const type of mimeTypes) {
        if (MediaRecorder.isTypeSupported(type)) {
          mimeType = type;
          break;
        }
      }
      
      console.log('Using MIME type:', mimeType || 'default');
      
      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: mimeType,
        audioBitsPerSecond: 64000  // Higher quality for better transcription
      });
      
      // Set up data handler BEFORE starting
      mediaRecorder.ondataavailable = (event) => {
        console.log(`📊 Data available event: size=${event.data.size}, state=${mediaRecorder.state}`);
        
        if (event.data.size > 0) {
          console.log(`✅ Got audio data: ${event.data.size} bytes`);
          
          if (ws?.readyState === WebSocket.OPEN && sessionId && isRecordingRef.current) {
            chunkNumberRef.current++;
            console.log(`📤 Sending chunk ${chunkNumberRef.current}, size: ${event.data.size}`);
            
            const reader = new FileReader();
            reader.onload = () => {
              const base64Data = reader.result.split(',')[1];
              const message = {
                type: 'audio_chunk',
                session_id: sessionId,
                data: base64Data,
                chunk: chunkNumberRef.current,
                size: event.data.size,
                timestamp: Date.now()
              };
              console.log(`📨 Sending message type: ${message.type}, chunk: ${message.chunk}`);
              ws.send(JSON.stringify(message));
            };
            reader.onerror = (err) => {
              console.error('❌ FileReader error:', err);
            };
            reader.readAsDataURL(event.data);
          } else {
            console.warn(`⚠️ Cannot send: ws=${ws?.readyState}, sessionId=${!!sessionId}, recording=${isRecordingRef.current}`);
          }
        }
      };
      
      mediaRecorder.onerror = (event) => {
        console.error('❌ MediaRecorder error:', event.error);
      };
      
      mediaRecorder.onstart = () => {
        console.log('✅ MediaRecorder started successfully');
      };
      
      // Start recording with 3-second chunks
      mediaRecorder.start(3000);
      console.log('MediaRecorder.start() called with timeslice 3000ms');
      
      mediaRecorderRef.current = mediaRecorder;
      setIsRecording(true);
      isRecordingRef.current = true;
      recordingStartTimeRef.current = Date.now();
      
      addTranscriptMessage('system', '🎙️ Recording started - Speaking detected');
      
      // Debug: Check every second if data is being collected
      const interval = setInterval(() => {
        if (isRecordingRef.current) {
          console.log(`⏱️ Recording active for ${((Date.now() - recordingStartTimeRef.current) / 1000).toFixed(1)}s, chunks sent: ${chunkNumberRef.current}`);
        } else {
          clearInterval(interval);
        }
      }, 2000);
      
    } catch (error) {
      console.error('❌ Microphone error:', error);
      setMicError(error.message);
      addTranscriptMessage('system', `❌ Microphone error: ${error.message}`);
    }
  };

  const stopRecording = () => {
    console.log('⏹️ Stopping recording...');
    console.log('Current session ID:', sessionId);
    console.log('Chunks sent:', chunkNumberRef.current);
    
    isRecordingRef.current = false;
    
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      console.log('Stopping MediaRecorder...');
      mediaRecorderRef.current.stop();
      mediaRecorderRef.current = null;
    }
    
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }
    
    if (volumeIntervalRef.current) {
      clearInterval(volumeIntervalRef.current);
      volumeIntervalRef.current = null;
    }
    
    setIsRecording(false);
    setVolume(0);
    
    if (chunkNumberRef.current === 0) {
      addTranscriptMessage('system', '⚠️ No audio was captured. Please check microphone permissions and try again.');
      setIsGenerating(false);
      return;
    }
    
    setIsGenerating(true);
    
    // Wait for final chunks
    setTimeout(() => {
      if (ws?.readyState === WebSocket.OPEN && sessionId) {
        const endMsg = {
          type: 'end_meeting',
          session_id: sessionId,
          total_chunks: chunkNumberRef.current,
          timestamp: Date.now()
        };
        console.log('📝 Sending end_meeting:', endMsg);
        ws.send(JSON.stringify(endMsg));
        addTranscriptMessage('system', `📝 Generating minutes from ${chunkNumberRef.current} audio chunks...`);
      } else {
        console.error('Cannot send end_meeting - WebSocket state:', ws?.readyState, 'SessionId:', sessionId);
      }
    }, 4000);
  };

  const clearMeeting = () => {
    isRecordingRef.current = false;
    
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop();
      mediaRecorderRef.current = null;
    }
    
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }
    
    if (volumeIntervalRef.current) {
      clearInterval(volumeIntervalRef.current);
      volumeIntervalRef.current = null;
    }
    
    setIsRecording(false);
    setIsGenerating(false);
    setMicError(null);
    setVolume(0);
    chunkNumberRef.current = 0;
    
    setTranscript([]);
    setActionItems([]);
    setDecisions([]);
    setDiscussionPoints([]);
    setSentiment('neutral');
    
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.close();
    }
    
    setTimeout(() => {
      connectWebSocket();
    }, 500);
    
    addTranscriptMessage('system', '🔄 Meeting cleared. Ready for new meeting.');
  };

  const getSentimentEmoji = () => {
    switch(sentiment) {
      case 'positive': return '😊';
      case 'negative': return '😟';
      default: return '😐';
    }
  };

  const getSentimentColor = () => {
    switch(sentiment) {
      case 'positive': return '#10b981';
      case 'negative': return '#ef4444';
      default: return '#f59e0b';
    }
  };

  return (
    <div className="app">
      <header className="header">
        <div className="header-content">
          <div className="logo-section">
            <div className="logo">🎙️</div>
            <div>
              <h1>meetingAiHackathon</h1>
              <p className="subtitle">Real-time meeting intelligence with audio streaming</p>
            </div>
          </div>
          
          <div className="status-section">
            <div className={`connection-status ${isConnected ? 'connected' : 'disconnected'}`}>
              <span className="status-dot"></span>
              <span>{isConnected ? 'Connected' : 'Connecting...'}</span>
            </div>
            <div className="model-badges">
              <span className="badge">Whisper base.en (244M)</span>
              <span className="badge">Phi-3 3.8B</span>
              <span className="badge">Real-time Streaming</span>
            </div>
          </div>
        </div>
      </header>

      <main className="main">
        <div className="container">
          <div className="controls-card">
            <div className="controls-content">
              <button 
                className={`btn-record ${isRecording ? 'recording' : ''}`}
                onClick={isRecording ? stopRecording : startRecording}
                disabled={!isConnected || isGenerating}
              >
                {isRecording ? '⏹️ End Meeting' : '🎤 Start Meeting'}
              </button>
              
              {micError && (
                <div className="error-message">
                  ⚠️ {micError}
                </div>
              )}
              
              {isRecording && (
                <div className="recording-indicator">
                  <div className="recording-pulse"></div>
                  <span>🎙️ Volume: {Math.round(volume * 100)}% | Streaming 3s chunks</span>
                </div>
              )}
              
              {isGenerating && (
                <div className="generating-indicator">
                  <div className="spinner"></div>
                  <span>Generating minutes from transcript...</span>
                </div>
              )}
              
              <button className="btn-clear" onClick={clearMeeting}>
                Clear
              </button>
            </div>
          </div>

          <div className="two-columns">
            <div className="column transcript-column">
              <div className="column-header">
                <h2>📝 Live Transcript</h2>
                <span className="message-count">{transcript.length} messages</span>
              </div>
              <div className="transcript-list">
                {transcript.length === 0 ? (
                  <div className="empty-state">
                    <div className="empty-icon">🎙️</div>
                    <p>Click "Start Meeting" to begin</p>
                    <p className="empty-sub">Audio streams in 3-second chunks</p>
                  </div>
                ) : (
                  transcript.map((item) => (
                    <div key={item.id} className={`transcript-message ${item.speaker === 'system' ? 'system' : ''}`}>
                      <div className="message-header">
                        <span className="message-speaker">{item.speaker}</span>
                        <span className="message-time">{item.timestamp}</span>
                      </div>
                      <div className="message-text">{item.text}</div>
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="column insights-column">
              <div className="column-header">
                <h2>📊 Meeting Insights</h2>
              </div>
              
              <div className="insights-list">
                <div className="insight-card sentiment-card" style={{ borderLeftColor: getSentimentColor() }}>
                  <div className="card-header">
                    <span className="card-icon">📊</span>
                    <h3>Sentiment</h3>
                  </div>
                  <div className="sentiment-value" style={{ color: getSentimentColor() }}>
                    {getSentimentEmoji()} {sentiment.toUpperCase()}
                  </div>
                </div>

                <div className="insight-card">
                  <div className="card-header">
                    <span className="card-icon">✅</span>
                    <h3>Action Items</h3>
                    <span className="item-count">{actionItems.length}</span>
                  </div>
                  <ul className="insight-list">
                    {actionItems.length > 0 ? (
                      actionItems.map((item, idx) => (
                        <li key={idx}>
                          <span className="bullet">📌</span>
                          <span>{item}</span>
                        </li>
                      ))
                    ) : (
                      <li className="empty-item">End meeting to see action items</li>
                    )}
                  </ul>
                </div>

                <div className="insight-card">
                  <div className="card-header">
                    <span className="card-icon">📋</span>
                    <h3>Decisions</h3>
                    <span className="item-count">{decisions.length}</span>
                  </div>
                  <ul className="insight-list">
                    {decisions.length > 0 ? (
                      decisions.map((decision, idx) => (
                        <li key={idx}>
                          <span className="bullet">✓</span>
                          <span>{decision}</span>
                        </li>
                      ))
                    ) : (
                      <li className="empty-item">No decisions yet</li>
                    )}
                  </ul>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>

      <footer className="footer">
        <div className="footer-content">
          <p className="motto">🕊️ <em>"Build something that shouldn't work — but does."</em></p>
          <p className="model-declaration">Models: Whisper base.en (244M) + Phi-3-mini (3.8B) • Real-time streaming • Cost: $0.000/meeting</p>
        </div>
      </footer>
    </div>
  );
}

export default App;