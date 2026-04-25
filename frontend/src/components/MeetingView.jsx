import React from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer
} from 'recharts';

const MeetingView = ({ transcript, actionItems, decisions, discussionPoints, sentiment }) => {
  const sentimentColor = {
    positive: '#4caf50',
    neutral: '#ff9800',
    negative: '#f44336'
  }[sentiment] || '#999';

  return (
    <div className="meeting-view">
      <div className="transcript-section">
        <h3>📝 Live Transcript</h3>
        <div className="transcript-container">
          {transcript.slice(-20).map((item, idx) => (
            <div key={idx} className={`transcript-item ${item.isFinal ? 'final' : 'partial'}`}>
              <span className="speaker">{item.speaker}:</span>
              <span className="text">{item.text}</span>
              {!item.isFinal && <span className="partial-badge">...</span>}
            </div>
          ))}
        </div>
      </div>

      <div className="insights-section">
        <div className="sentiment-card" style={{ borderColor: sentimentColor }}>
          <h4>📊 Meeting Sentiment</h4>
          <div className="sentiment-value" style={{ color: sentimentColor }}>
            {sentiment.toUpperCase()}
          </div>
          <ResponsiveContainer width="100%" height={60}>
            <LineChart data={[{ value: sentiment === 'positive' ? 80 : sentiment === 'negative' ? 20 : 50 }]}>
              <CartesianGrid strokeDasharray="3 3" />
              <Line type="monotone" dataKey="value" stroke={sentimentColor} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="actions-card">
          <h4>✅ Action Items</h4>
          <ul>
            {actionItems.length > 0 ? (
              actionItems.map((item, idx) => <li key={idx}>📌 {item}</li>)
            ) : (
              <li className="empty">No action items yet</li>
            )}
          </ul>
        </div>

        <div className="decisions-card">
          <h4>📋 Decisions</h4>
          <ul>
            {decisions.length > 0 ? (
              decisions.map((decision, idx) => <li key={idx}>✓ {decision}</li>)
            ) : (
              <li className="empty">No decisions recorded</li>
            )}
          </ul>
        </div>

        <div className="discussion-card">
          <h4>💬 Key Discussion Points</h4>
          <ul>
            {discussionPoints.length > 0 ? (
              discussionPoints.map((point, idx) => <li key={idx}>• {point}</li>)
            ) : (
              <li className="empty">No discussion points yet</li>
            )}
          </ul>
        </div>
      </div>
    </div>
  );
};

export default MeetingView;