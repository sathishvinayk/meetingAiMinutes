FROM golang:1.21-alpine AS builder

WORKDIR /app

# Copy go mod files
COPY go.mod go.sum ./
RUN go mod download

# Copy all source code (including pre-generated pb/*.pb.go files)
COPY . .

# Build the application
RUN CGO_ENABLED=0 go build -v -o backend .

FROM alpine:latest

RUN apk --no-cache add ca-certificates

WORKDIR /root/

COPY --from=builder /app/backend .

EXPOSE 8080

CMD ["./backend"]