import React, { useState, useEffect, useRef, useCallback } from 'react';
import './App.css';

function App() {
  const [isRecording, setIsRecording] = useState(false);
  const [transcript, setTranscript] = useState([]);
  const [actionItems, setActionItems] = useState([]);
  const [decisions, setDecisions] = useState([]);
  const [, setDiscussionPoints] = useState([]);
  const [sentiment, setSentiment] = useState('neutral');
  const [sessionId, setSessionId] = useState(null);
  const [ws, setWs] = useState(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [micError, setMicError] = useState(null);
  const mediaRecorderRef = useRef(null);
  const streamRef = useRef(null);
  const recordingStartTimeRef = useRef(null);
  const chunkNumberRef = useRef(0);
  const isRecordingRef = useRef(false); // Use ref to avoid closure issues

  const addTranscriptMessage = useCallback((speaker, text) => {
    setTranscript(prev => [...prev, {
      id: Date.now(),
      speaker: speaker,
      text: text,
      timestamp: new Date().toLocaleTimeString()
    }]);
  }, []);

  // In your App component, update the WebSocket handler
const connectWebSocket = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const websocket = new WebSocket(`${protocol}//localhost:8080/ws`);
    
    websocket.onopen = () => {
        console.log('✅ WebSocket connected');
        setIsConnected(true);
        setMicError(null);
    };
    
    websocket.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            console.log('📨 Full message received:', JSON.stringify(data, null, 2));
            
            switch (data.type) {
                case 'session_init':
                    const newSessionId = data.session_id;
                    setSessionId(newSessionId);
                    console.log('🎯 Session initialized with ID:', newSessionId);
                    addTranscriptMessage('system', `New meeting session started: ${newSessionId.slice(-8)}`);
                    break;
                    
                case 'transcription':
                    console.log('📝 Transcription received:', data.text);
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
    
    websocket.onclose = () => {
        console.log('WebSocket disconnected');
        setIsConnected(false);
        // Reconnect after 3 seconds
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
    };
  }, [connectWebSocket]);

  const startRecording = async () => {
    setMicError(null);
    chunkNumberRef.current = 0;
    
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ 
            audio: {
                echoCancellation: false,
                noiseSuppression: false,
                autoGainControl: false,
                channelCount: 1,
                sampleRate: 16000
            }
        });
        
        streamRef.current = stream;
        
        // Use a consistent format - force WebM throughout
        let mimeType = 'audio/webm';
        if (!MediaRecorder.isTypeSupported('audio/webm')) {
            mimeType = 'audio/mp4';
        }
        
        console.log('Using MIME type:', mimeType);
        
        const mediaRecorder = new MediaRecorder(stream, {
            mimeType: mimeType,
            audioBitsPerSecond: 128000
        });
        
        // Collect ALL chunks and combine them
        let allChunks = [];
        
        mediaRecorder.ondataavailable = (event) => {
          if (event.data.size > 0 && ws?.readyState === WebSocket.OPEN && sessionId) {
              chunkNumberRef.current++;
              console.log(`📤 Sending chunk ${chunkNumberRef.current}, size: ${event.data.size}, session: ${sessionId}`);
              
              const reader = new FileReader();
              reader.onload = () => {
                  const base64Data = reader.result.split(',')[1];
                  const audioMsg = {
                      type: 'audio_chunk',
                      session_id: sessionId,  // Use the current session ID
                      data: base64Data,
                      chunk: chunkNumberRef.current,
                      size: event.data.size,
                      timestamp: Date.now()
                  };
                  ws.send(JSON.stringify(audioMsg));
              };
              reader.readAsDataURL(event.data);
          }
      };
        
        mediaRecorder.onstop = async () => {
            console.log(`🎬 Recording stopped. Total chunks: ${allChunks.length}`);
            
            if (allChunks.length === 0) {
                console.error('No audio chunks collected');
                return;
            }
            
            // Combine all chunks into a single blob
            const fullAudioBlob = new Blob(allChunks, { type: mimeType });
            console.log(`📦 Combined audio: ${fullAudioBlob.size} bytes`);
            
            // Convert to base64 and send as a single chunk
            const reader = new FileReader();
            reader.onload = () => {
                const base64Data = reader.result.split(',')[1];
                if (ws?.readyState === WebSocket.OPEN && sessionId) {
                    ws.send(JSON.stringify({
                        type: 'audio_chunk',
                        session_id: sessionId,
                        data: base64Data,
                        chunk: 1,
                        size: fullAudioBlob.size,
                        is_final: true
                    }));
                    console.log(`📤 Sent complete audio (${fullAudioBlob.size} bytes)`);
                }
            };
            reader.readAsDataURL(fullAudioBlob);
        };
        
        // Don't send partial chunks - collect all and send at once
        mediaRecorder.start(10000); // Collect up to 10 seconds
        mediaRecorderRef.current = mediaRecorder;
        setIsRecording(true);
        recordingStartTimeRef.current = Date.now();
        addTranscriptMessage('system', '🎙️ Recording started - Audio will be processed when stopped');
        
    } catch (error) {
        console.error('Microphone error:', error);
        setMicError(error.message);
    }
  };

  const stopRecording = () => {
    console.log('⏹️ Stopping recording...');
    console.log('Current session ID:', sessionId);
    
    isRecordingRef.current = false;
    
    // Collect all chunks from MediaRecorder
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
        mediaRecorderRef.current.stop();
        mediaRecorderRef.current = null;
    }
    
    if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop());
        streamRef.current = null;
    }
    
    setIsRecording(false);
    setIsGenerating(true);
    
    // Wait for the final audio chunk to be sent
    setTimeout(() => {
        if (ws?.readyState === WebSocket.OPEN && sessionId) {
            const endMsg = {
                type: 'end_meeting',
                session_id: sessionId,  // Use the correct session ID
                timestamp: Date.now()
            };
            console.log('📝 Sending end_meeting:', endMsg);
            ws.send(JSON.stringify(endMsg));
            addTranscriptMessage('system', '📝 Generating minutes from transcript...');
        } else {
            console.error('Cannot send end_meeting - WebSocket state:', ws?.readyState, 'SessionId:', sessionId);
        }
    }, 2000);
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
    
    setIsRecording(false);
    setIsGenerating(false);
    setMicError(null);
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
              <h1>MeetingPulse</h1>
              <p className="subtitle">Real-time meeting intelligence with audio streaming</p>
            </div>
          </div>
          
          <div className="status-section">
            <div className={`connection-status ${isConnected ? 'connected' : 'disconnected'}`}>
              <span className="status-dot"></span>
              <span>{isConnected ? 'Connected' : 'Connecting...'}</span>
            </div>
            <div className="model-badges">
              <span className="badge">Whisper 74M</span>
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
                  <span>Streaming audio in real-time... (2s chunks)</span>
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
                    <p className="empty-sub">Audio streams in 2-second chunks</p>
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
          <p className="model-declaration">Models: Whisper Tiny (74M) + Phi-3-mini (3.8B) • Real-time streaming • Cost: $0.000/meeting</p>
        </div>
      </footer>
    </div>
  );
}

export default App;