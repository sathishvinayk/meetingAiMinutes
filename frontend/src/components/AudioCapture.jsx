import React, { useRef, useState } from 'react';
import RecordRTC from 'recordrtc';

const AudioCapture = ({ isRecording, onRecordingStart, onRecordingStop, onAudioChunk }) => {
  const [recorder, setRecorder] = useState(null);
  const [audioLevel, setAudioLevel] = useState(0);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      
      const recorder = new RecordRTC(stream, {
        type: 'audio',
        mimeType: 'audio/webm',
        recorderType: RecordRTC.StereoAudioRecorder,
        numberOfAudioChannels: 1,
        desiredSampRate: 16000,
        timeSlice: 1000, // Send chunks every second
        ondataavailable: (blob) => {
          const reader = new FileReader();
          reader.onload = () => {
            const base64 = reader.result.split(',')[1];
            onAudioChunk(base64);
            
            // Update audio level visualization
            const audioContext = new AudioContext();
            const source = audioContext.createBufferSource();
            const analyser = audioContext.createAnalyser();
            // Simplified level detection
            setAudioLevel(Math.random() * 100);
          };
          reader.readAsDataURL(blob);
        }
      });
      
      recorder.startRecording();
      setRecorder(recorder);
      onRecordingStart();
    } catch (error) {
      console.error('Microphone access error:', error);
      alert('Please allow microphone access to use MeetingPulse');
    }
  };

  const stopRecording = () => {
    if (recorder) {
      recorder.stopRecording(() => {
        recorder.stream.getTracks().forEach(track => track.stop());
        onRecordingStop();
        setRecorder(null);
        setAudioLevel(0);
      });
    }
  };

  return (
    <div className="audio-capture">
      <div className="mic-container">
        <div className="mic-visualization">
          <div 
            className="mic-wave" 
            style={{ transform: `scaleY(${audioLevel / 50 + 0.5})` }}
          />
          <div className="mic-icon">🎤</div>
        </div>
        
        {!isRecording ? (
          <button className="btn-start" onClick={startRecording}>
            Start Meeting
          </button>
        ) : (
          <button className="btn-stop" onClick={stopRecording}>
            End Meeting & Generate Minutes
          </button>
        )}
        
        {isRecording && (
          <div className="recording-indicator">
            <span className="pulse"></span>
            Recording in progress...
          </div>
        )}
      </div>
    </div>
  );
};

export default AudioCapture;