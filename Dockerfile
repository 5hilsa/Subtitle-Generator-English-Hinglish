# Cloud GPU image: faster-whisper on an NVIDIA GPU (CUDA 12 + cuDNN 9).
# Build:  docker build -t hinglish-captions .
# Run:    docker run --gpus all -p 7860:7860 --env-file .env -v captions-data:/app/data hinglish-captions
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 PORT=7860 SUBGEN_NO_BROWSER=1 SUBGEN_WARMUP=1 \
    SUBGEN_BACKEND=faster-whisper DATA_DIR=/app/data HF_HOME=/app/data/models
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt gunicorn
COPY . .

EXPOSE 7860
# One worker process: jobs and the GPU lock live in memory. Threads handle concurrent users.
CMD ["sh", "-c", "gunicorn -w 1 --threads 16 --timeout 0 -b 0.0.0.0:${PORT} app:app"]
