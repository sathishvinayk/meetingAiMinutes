FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# Install setuptools first
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install NumPy 1.x specifically (compatible with Whisper)
RUN pip install --no-cache-dir numpy==1.24.3

# Install PyTorch (CPU version)
RUN pip install --no-cache-dir torch==2.0.1 torchaudio==2.0.2 --index-url https://download.pytorch.org/whl/cpu

# Install Whisper and other dependencies
RUN pip install --no-cache-dir openai-whisper requests grpcio grpcio-tools protobuf tqdm pydub

# Copy files
COPY proto/ ./proto/
COPY main.py .
COPY entrypoint.sh .

RUN chmod +x entrypoint.sh

EXPOSE 50051

ENTRYPOINT ["./entrypoint.sh"]
