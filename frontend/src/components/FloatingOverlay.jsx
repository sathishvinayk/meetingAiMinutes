import React, { useState } from 'react';

const FloatingOverlay = ({ actionItems, onClose }) => {
  const [position, setPosition] = useState({ x: 20, y: 20 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });

  const handleMouseDown = (e) => {
    setIsDragging(true);
    setDragStart({
      x: e.clientX - position.x,
      y: e.clientY - position.y
    });
  };

  const handleMouseMove = (e) => {
    if (isDragging) {
      setPosition({
        x: e.clientX - dragStart.x,
        y: e.clientY - dragStart.y
      });
    }
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  React.useEffect(() => {
    if (isDragging) {
      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', handleMouseUp);
    }
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging]);

  return (
    <div 
      className="floating-overlay"
      style={{ left: position.x, top: position.y }}
    >
      <div className="overlay-header" onMouseDown={handleMouseDown}>
        <span>🎯 MeetingPulse Live</span>
        <button onClick={onClose} className="close-btn">×</button>
      </div>
      <div className="overlay-content">
        {actionItems.length > 0 ? (
          <>
            <strong>Action Items:</strong>
            <ul>
              {actionItems.slice(0, 3).map((item, idx) => (
                <li key={idx}>{item.substring(0, 50)}...</li>
              ))}
            </ul>
          </>
        ) : (
          <p>Waiting for action items...</p>
        )}
      </div>
    </div>
  );
};

export default FloatingOverlay;