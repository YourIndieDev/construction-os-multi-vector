FROM pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/service \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/huggingface \
    TRANSFORMERS_CACHE=/models/huggingface \
    TOKENIZERS_PARALLELISM=false

WORKDIR /service

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY app ./app
COPY tests ./tests

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]