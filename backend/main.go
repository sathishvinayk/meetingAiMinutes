package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"
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
	Ending      bool
	Sequence    int32
}

type Hub struct {
	sessions  map[string]*Session
	mu        sync.RWMutex
	grpcConn  pb.MeetingServiceClient
	grpcCC    *grpc.ClientConn
	grpcReady bool
}

func NewHub() *Hub {
	log.Println("🔌 Attempting to connect to ML service at ml-service:50051...")

	var conn *grpc.ClientConn
	var err error

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

	go func(s *Session, sid string) {
		for {
			resp, err := s.Stream.Recv()
			if err == io.EOF {
				log.Printf("📭 [%s] Stream EOF received", sid)
				return
			}
			if err != nil {
				if !s.Ending {
					log.Printf("⚠️ [%s] Stream receive error: %v", sid, err)
				}
				s.StreamReady = false
				return
			}

			log.Printf("📝 [%s] ML Transcription: '%s' (confidence: %.2f, final: %v)",
				sid, resp.Text, resp.Confidence, resp.IsFinal)

			s.mu.Lock()
			if resp.IsFinal && resp.Text != "" && resp.Text != "🎤 Listening..." {
				s.Transcript = append(s.Transcript, resp.Text)
				log.Printf("✅ [%s] Added to transcript (total: %d entries)", sid, len(s.Transcript))
			}
			s.mu.Unlock()

			err = s.Conn.WriteJSON(map[string]interface{}{
				"type":       "transcription",
				"text":       resp.Text,
				"speaker":    fmt.Sprintf("Speaker %d", resp.SpeakerId),
				"confidence": resp.Confidence,
				"is_final":   resp.IsFinal,
			})
			if err != nil {
				log.Printf("❌ [%s] Failed to send transcription to client: %v", sid, err)
			}
		}
	}(session, shortID)

	return nil
}

func (h *Hub) HandleWebSocket(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("❌ WebSocket error: %v", err)
		return
	}
	defer conn.Close()

	sessionID := fmt.Sprintf("session_%d", time.Now().UnixNano())
	shortID := sessionID[len(sessionID)-8:]

	log.Printf("============================================================")
	log.Printf("📱 [%s] NEW SESSION CREATED", shortID)
	log.Printf("   Full Session ID: %s", sessionID)
	log.Printf("   Time: %v", time.Now())
	log.Printf("============================================================")

	session := &Session{
		ID:          sessionID,
		Conn:        conn,
		Transcript:  make([]string, 0),
		ChunkCount:  0,
		AudioBuffer: make([][]byte, 0),
		StreamReady: false,
		Ending:      false,
		Sequence:    0,
	}

	h.mu.Lock()
	h.sessions[sessionID] = session
	h.mu.Unlock()

	// Send session init with FULL ID
	initMsg := map[string]interface{}{
		"type":       "session_init",
		"session_id": sessionID,
	}
	if err := conn.WriteJSON(initMsg); err != nil {
		log.Printf("❌ [%s] Failed to send session init: %v", shortID, err)
		return
	}
	log.Printf("✅ [%s] Session init sent with ID: %s", shortID, sessionID)

	if h.grpcReady {
		if err := h.createStream(session, shortID); err != nil {
			log.Printf("⚠️ [%s] Initial stream creation failed: %v", shortID, err)
		}
	}

	// Stream recovery goroutine
	go func() {
		for i := 0; i < 20; i++ {
			time.Sleep(2 * time.Second)
			if session.StreamReady {
				return
			}
			if h.grpcReady && session.Stream == nil {
				log.Printf("🔄 [%s] Attempting to recover stream (attempt %d)", shortID, i+1)
				if err := h.createStream(session, shortID); err == nil {
					session.mu.Lock()
					buffered := session.AudioBuffer
					session.AudioBuffer = make([][]byte, 0)
					session.mu.Unlock()

					for _, audio := range buffered {
						session.Sequence++
						err := session.Stream.Send(&pb.AudioChunk{
							Data:      audio,
							SessionId: sessionID,
							Sequence:  session.Sequence,
						})
						if err != nil {
							log.Printf("❌ [%s] Failed to send buffered chunk: %v", shortID, err)
						}
					}
					log.Printf("✅ [%s] Stream recovered, sent %d buffered chunks", shortID, len(buffered))
					return
				}
			}
		}
		log.Printf("⚠️ [%s] Could not establish gRPC stream after retries", shortID)
	}()

	for {
		var msg map[string]interface{}
		err := conn.ReadJSON(&msg)
		if err != nil {
			log.Printf("❌ [%s] WebSocket read error: %v", shortID, err)
			break
		}

		msgType, ok := msg["type"].(string)
		if !ok {
			log.Printf("⚠️ [%s] Received message without type field", shortID)
			continue
		}

		log.Printf("📨 [%s] Received message type: %s", shortID, msgType)

		switch msgType {
		case "audio_chunk":
			session.mu.Lock()
			session.ChunkCount++

			msgSessionID, _ := msg["session_id"].(string)
			log.Printf("🎤 [%s] Audio chunk %d received", shortID, session.ChunkCount)
			log.Printf("   Message session_id: '%s'", msgSessionID)
			log.Printf("   Expected session_id: '%s'", sessionID)
			log.Printf("   Match: %v", msgSessionID == sessionID)

			if data, ok := msg["data"].(string); ok && data != "" {
				audioData, err := base64.StdEncoding.DecodeString(data)
				if err == nil {
					log.Printf("   Audio size: %d bytes", len(audioData))
					if len(audioData) > 4 {
						log.Printf("   First 20 bytes (hex): %x", audioData[:min(20, len(audioData))])
						// Detect audio format
						if len(audioData) > 4 {
							if audioData[0] == 0x1a && audioData[1] == 0x45 {
								log.Printf("   Format: WebM/Matroska detected")
							} else if audioData[0] == 0x66 && audioData[1] == 0x74 {
								log.Printf("   Format: MP4/M4A detected")
							} else if audioData[0] == 0x52 && audioData[1] == 0x49 {
								log.Printf("   Format: WAV detected")
							} else {
								log.Printf("   Format: Unknown/RAW")
							}
						}
					}

					if session.StreamReady && session.Stream != nil && !session.Ending {
						session.Sequence++
						err := session.Stream.Send(&pb.AudioChunk{
							Data:      audioData,
							SessionId: sessionID,
							Sequence:  session.Sequence,
						})
						if err != nil {
							log.Printf("❌ [%s] Failed to send chunk to ML: %v", shortID, err)
						} else {
							log.Printf("✅ [%s] Chunk %d sent to ML service", shortID, session.Sequence)
						}
					} else {
						log.Printf("💾 [%s] Buffering chunk (StreamReady=%v, Ending=%v)",
							shortID, session.StreamReady, session.Ending)
						session.AudioBuffer = append(session.AudioBuffer, audioData)
						log.Printf("   Buffer now has %d chunks total", len(session.AudioBuffer))
					}
				} else {
					log.Printf("❌ [%s] Base64 decode error: %v", shortID, err)
				}
			} else {
				log.Printf("⚠️ [%s] No data field in audio_chunk", shortID)
			}
			session.mu.Unlock()

		case "end_meeting":
			log.Printf("🏁 [%s] End meeting signal received", shortID)
			session.Ending = true

			// Wait for pending transcriptions
			log.Printf("⏳ [%s] Waiting 2 seconds for final transcriptions...", shortID)
			time.Sleep(2 * time.Second)

			if session.Stream != nil {
				session.Stream.CloseSend()
				log.Printf("📤 [%s] Closed gRPC send stream", shortID)
			}

			session.mu.Lock()
			fullTranscript := strings.Join(session.Transcript, " ")
			log.Printf("📄 [%s] Full transcript (%d entries): '%s'", shortID, len(session.Transcript), fullTranscript)
			session.mu.Unlock()

			var actionItems, decisions, discussionPoints []string
			sentiment := "neutral"

			if h.grpcReady && len(fullTranscript) > 10 {
				log.Printf("🤖 [%s] Calling GenerateMinutes with transcript length %d", shortID, len(fullTranscript))
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
					log.Printf("✅ [%s] Received minutes: %d action items, %d decisions",
						shortID, len(actionItems), len(decisions))
				}
			} else {
				log.Printf("⚠️ [%s] Cannot generate minutes: grpcReady=%v, transcript_len=%d",
					shortID, h.grpcReady, len(fullTranscript))
			}

			if len(actionItems) == 0 {
				log.Printf("⚠️ [%s] No action items found, using fallback", shortID)
				if len(session.Transcript) > 0 {
					for _, t := range session.Transcript {
						shortText := t
						if len(shortText) > 100 {
							shortText = shortText[:100]
						}
						actionItems = append(actionItems, shortText)
					}
				} else {
					actionItems = []string{"No speech detected. Please ensure microphone works and speak clearly."}
				}
				decisions = []string{"No decisions recorded"}
				discussionPoints = []string{"No discussion points recorded"}
			}

			minutesMsg := map[string]interface{}{
				"type": "minutes",
				"payload": map[string]interface{}{
					"action_items":      actionItems,
					"decisions":         decisions,
					"discussion_points": discussionPoints,
					"sentiment":         sentiment,
				},
			}

			log.Printf("📤 [%s] Sending minutes to client: %v", shortID, minutesMsg)

			if err := conn.WriteJSON(minutesMsg); err != nil {
				log.Printf("❌ [%s] Failed to send minutes: %v", shortID, err)
			} else {
				log.Printf("✅ [%s] Minutes sent successfully to client", shortID)
			}
		}
	}

	h.mu.Lock()
	delete(h.sessions, sessionID)
	h.mu.Unlock()
	log.Printf("👋 [%s] Session cleaned up", shortID)
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
