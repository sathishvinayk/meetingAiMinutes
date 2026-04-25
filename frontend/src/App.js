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
  const mediaRecorderRef = useRef(null);
  const streamRef = useRef(null);

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
      console.log('✅ WebSocket connected');
      setIsConnected(true);
    };
    
    websocket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        switch (data.type) {
          case 'session_init':
            setSessionId(data.session_id);
            addTranscriptMessage('system', 'New meeting session started');
            break;
            
          case 'transcription':
            addTranscriptMessage(data.speaker || 'speaker', data.text);
            break;
            
          case 'minutes':
            if (data.payload) {
              setActionItems(data.payload.action_items || []);
              setDecisions(data.payload.decisions || []);
              setDiscussionPoints(data.payload.discussion_points || []);
              setSentiment(data.payload.sentiment || 'neutral');
              setIsGenerating(false);
              addTranscriptMessage('system', '✅ Meeting minutes generated!');
            }
            break;
            
          default:
            break;
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
      setTimeout(() => connectWebSocket(), 3000);
    };
    
    setWs(websocket);
    
    return websocket;
  }, [addTranscriptMessage]);

  useEffect(() => {
    connectWebSocket();
    
    return () => {
      if (ws) ws.close();
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop());
      }
    };
  }, []);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          sampleRate: 16000,
          channelCount: 1
        }
      });
      
      streamRef.current = stream;
      
      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: 'audio/webm'
      });
      
      mediaRecorder.ondataavailable = async (event) => {
        if (event.data.size > 0 && ws?.readyState === WebSocket.OPEN && sessionId) {
          const reader = new FileReader();
          reader.onload = () => {
            const base64Data = reader.result.split(',')[1];
            ws.send(JSON.stringify({
              type: 'audio_chunk',
              session_id: sessionId,
              data: base64Data
            }));
          };
          reader.readAsDataURL(event.data);
        }
      };
      
      mediaRecorder.start(3000);
      mediaRecorderRef.current = mediaRecorder;
      setIsRecording(true);
      addTranscriptMessage('system', '🎙️ Recording started - Speak clearly');
      
    } catch (error) {
      console.error('Microphone error:', error);
      alert('Please allow microphone access to use MeetingPulse');
    }
  };

  const stopRecording = () => {
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
    addTranscriptMessage('system', '⏹️ Generating minutes...');
    
    if (ws?.readyState === WebSocket.OPEN && sessionId) {
      ws.send(JSON.stringify({
        type: 'end_meeting',
        session_id: sessionId
      }));
    }
  };

  const clearMeeting = () => {
    // Clear all state
    setTranscript([]);
    setActionItems([]);
    setDecisions([]);
    setDiscussionPoints([]);
    setSentiment('neutral');
    
    // Close current WebSocket and create a new session
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.close();
    }
    
    // Reconnect to get a fresh session
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
              <p className="subtitle">Real-time meeting intelligence</p>
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
              <span className="badge">MiniLM 22M</span>
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
              
              {isRecording && (
                <div className="recording-indicator">
                  <div className="recording-pulse"></div>
                  <span>Recording...</span>
                </div>
              )}
              
              {isGenerating && (
                <div className="generating-indicator">
                  <div className="spinner"></div>
                  <span>Generating minutes...</span>
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
          <p className="model-declaration">Models: Whisper Tiny (74M) + Phi-3-mini (3.8B) • Cost: $0.000/meeting</p>
        </div>
      </footer>
    </div>
  );
}

export default App;