package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"sync"
	"time"

	pb "meetingpulse/backend/pb"

	"github.com/gorilla/websocket"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool { return true },
}

type Session struct {
	ID          string
	Conn        *websocket.Conn
	Transcript  []string
	ChunkCount  int
	AudioBuffer [][]byte
	mu          sync.Mutex
	Stream      pb.MeetingService_ProcessAudioClient
	StreamCtx   context.Context
	CancelFunc  context.CancelFunc
	StreamReady bool
}

type Hub struct {
	sessions  map[string]*Session
	mu        sync.RWMutex
	grpcConn  pb.MeetingServiceClient
	grpcCC    *grpc.ClientConn
	grpcReady bool
	grpcMu    sync.RWMutex
}

func NewHub() *Hub {
	log.Println("🔌 Attempting to connect to ML service at ml-service:50051...")

	var conn *grpc.ClientConn
	var err error

	// Try to connect with retries
	for i := 0; i < 30; i++ {
		conn, err = grpc.Dial("ml-service:50051",
			grpc.WithTransportCredentials(insecure.NewCredentials()),
			grpc.WithTimeout(5*time.Second),
		)
		if err == nil {
			break
		}
		if i == 0 {
			log.Printf("⏳ Waiting for ML service to start...")
		}
		time.Sleep(1 * time.Second)
	}

	if err != nil {
		log.Printf("⚠️ Failed to connect to ML service: %v", err)
		return &Hub{
			sessions:  make(map[string]*Session),
			grpcReady: false,
		}
	}

	client := pb.NewMeetingServiceClient(conn)
	log.Println("✅ Connected to ML service via gRPC")

	return &Hub{
		sessions:  make(map[string]*Session),
		grpcConn:  client,
		grpcCC:    conn,
		grpcReady: true,
	}
}

func (h *Hub) Close() {
	if h.grpcCC != nil {
		h.grpcCC.Close()
	}
}

func (h *Hub) createStream(session *Session, shortID string) error {
	if !h.grpcReady {
		return fmt.Errorf("gRPC not ready")
	}

	session.StreamCtx, session.CancelFunc = context.WithCancel(context.Background())
	stream, err := h.grpcConn.ProcessAudio(session.StreamCtx)
	if err != nil {
		return err
	}
	session.Stream = stream
	session.StreamReady = true

	log.Printf("✅ [%s] gRPC stream established to ML service", shortID)

	// Receive transcriptions
	go func(s *Session, sid string) {
		for {
			resp, err := s.Stream.Recv()
			if err == io.EOF {
				return
			}
			if err != nil {
				log.Printf("⚠️ [%s] Stream receive error: %v", sid, err)
				s.StreamReady = false
				return
			}

			log.Printf("📝 [%s] ML Transcription: %s", sid, resp.Text)

			s.mu.Lock()
			if resp.IsFinal {
				s.Transcript = append(s.Transcript, resp.Text)
			}
			s.mu.Unlock()

			s.Conn.WriteJSON(map[string]interface{}{
				"type":       "transcription",
				"text":       resp.Text,
				"speaker":    fmt.Sprintf("Speaker %d", resp.SpeakerId),
				"confidence": resp.Confidence,
				"is_final":   resp.IsFinal,
			})
		}
	}(session, shortID)

	return nil
}

func (h *Hub) HandleWebSocket(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("WebSocket error: %v", err)
		return
	}
	defer conn.Close()

	sessionID := fmt.Sprintf("session_%d", time.Now().UnixNano())
	shortID := sessionID[len(sessionID)-8:]

	session := &Session{
		ID:          sessionID,
		Conn:        conn,
		Transcript:  make([]string, 0),
		ChunkCount:  0,
		AudioBuffer: make([][]byte, 0),
		StreamReady: false,
	}

	h.mu.Lock()
	h.sessions[sessionID] = session
	h.mu.Unlock()

	log.Printf("📱 [%s] New session started", shortID)

	defer func() {
		if session.CancelFunc != nil {
			session.CancelFunc()
		}
		h.mu.Lock()
		delete(h.sessions, sessionID)
		h.mu.Unlock()
		log.Printf("👋 [%s] Session ended", shortID)
	}()

	// Send session init
	conn.WriteJSON(map[string]interface{}{
		"type":       "session_init",
		"session_id": sessionID,
	})

	// Try to create stream immediately (may fail if ML not ready)
	if h.grpcReady {
		if err := h.createStream(session, shortID); err != nil {
			log.Printf("⚠️ [%s] Initial stream creation failed: %v", shortID, err)
		}
	}

	// Start a goroutine to retry stream creation if needed
	go func() {
		for i := 0; i < 20; i++ {
			time.Sleep(2 * time.Second)
			if session.StreamReady {
				return
			}
			if h.grpcReady && session.Stream == nil {
				if err := h.createStream(session, shortID); err == nil {
					// Stream created successfully, send buffered audio
					session.mu.Lock()
					buffered := session.AudioBuffer
					session.AudioBuffer = make([][]byte, 0)
					seq := int32(0)
					for _, audio := range buffered {
						seq++
						session.Stream.Send(&pb.AudioChunk{
							Data:      audio,
							SessionId: sessionID,
							Sequence:  seq,
						})
					}
					session.mu.Unlock()
					log.Printf("✅ [%s] Stream recovered, sent %d buffered chunks", shortID, len(buffered))
					return
				}
			}
		}
		log.Printf("⚠️ [%s] Could not establish gRPC stream after retries", shortID)
	}()

	sequence := int32(0)

	for {
		var msg map[string]interface{}
		err := conn.ReadJSON(&msg)
		if err != nil {
			break
		}

		switch msg["type"] {
		case "audio_chunk":
			session.mu.Lock()
			session.ChunkCount++

			if data, ok := msg["data"].(string); ok && data != "" {
				audioData, err := base64.StdEncoding.DecodeString(data)
				if err == nil {
					log.Printf("🎤 [%s] Audio chunk %d: %d bytes", shortID, session.ChunkCount, len(audioData))

					if session.StreamReady && session.Stream != nil {
						sequence++
						err := session.Stream.Send(&pb.AudioChunk{
							Data:      audioData,
							SessionId: sessionID,
							Sequence:  sequence,
						})
						if err != nil {
							log.Printf("❌ [%s] Failed to send audio: %v", shortID, err)
							session.StreamReady = false
							// Buffer for retry
							session.AudioBuffer = append(session.AudioBuffer, audioData)
						}
					} else {
						// Buffer audio for later
						session.AudioBuffer = append(session.AudioBuffer, audioData)
						log.Printf("💾 [%s] Buffered audio chunk (total: %d)", shortID, len(session.AudioBuffer))
					}
				}
			}
			session.mu.Unlock()

		case "end_meeting":
			log.Printf("📝 [%s] Ending meeting, generating minutes...", shortID)

			// Close stream
			if session.Stream != nil {
				session.Stream.CloseSend()
			}

			// Build transcript
			session.mu.Lock()
			fullTranscript := ""
			for _, text := range session.Transcript {
				fullTranscript += text + " "
			}
			session.mu.Unlock()

			log.Printf("📄 [%s] Full transcript: %s", shortID, fullTranscript[:min(200, len(fullTranscript))])

			var actionItems, decisions, discussionPoints []string
			sentiment := "neutral"

			// Try to get minutes from ML service
			if h.grpcReady && len(fullTranscript) > 50 {
				req := &pb.TranscriptRequest{
					SessionId:  sessionID,
					Transcript: fullTranscript,
				}
				resp, err := h.grpcConn.GenerateMinutes(context.Background(), req)
				if err != nil {
					log.Printf("❌ [%s] Failed to generate minutes: %v", shortID, err)
				} else {
					actionItems = resp.ActionItems
					decisions = resp.Decisions
					discussionPoints = resp.DiscussionPoints
					sentiment = resp.Sentiment
					log.Printf("✅ [%s] Received minutes from ML service", shortID)
				}
			}

			// Fallback if no transcript
			if len(actionItems) == 0 {
				if len(session.Transcript) > 0 {
					for _, t := range session.Transcript {
						actionItems = append(actionItems, t[:min(100, len(t))])
					}
				}
				if len(actionItems) == 0 {
					actionItems = []string{"Speak during the meeting to generate action items"}
				}
				decisions = []string{"No decisions recorded"}
				discussionPoints = []string{"No discussion points recorded"}
			}

			conn.WriteJSON(map[string]interface{}{
				"type": "minutes",
				"payload": map[string]interface{}{
					"action_items":      actionItems,
					"decisions":         decisions,
					"discussion_points": discussionPoints,
					"sentiment":         sentiment,
				},
			})
			log.Printf("✅ [%s] Minutes sent to client", shortID)
		}
	}
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func main() {
	hub := NewHub()
	defer hub.Close()

	http.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		if r.Method == "OPTIONS" {
			w.WriteHeader(http.StatusOK)
			return
		}
		hub.HandleWebSocket(w, r)
	})

	http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"status":    "ok",
			"timestamp": time.Now().Format(time.RFC3339),
		})
	})

	port := ":8080"
	log.Printf("🚀 Backend server running on %s", port)
	log.Printf("🔌 WebSocket: ws://localhost%s/ws", port)
	log.Printf("💚 Health: http://localhost%s/health", port)
	log.Printf("✅ Ready to accept connections")

	if err := http.ListenAndServe(port, nil); err != nil {
		log.Fatal("Server error:", err)
	}
}
