FROM python:3.11-slim

LABEL org.opencontainers.image.title="motor-metrics-mock" \
      org.opencontainers.image.description="Mock Prometheus exporter that emits pymotor-shaped metrics (vllm:* / motor_* / http_* / npu_chip_info_*) for dashboard development." \
      org.opencontainers.image.source="https://gitcode.com/Ascend/mind-cluster"

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MOCK_SPECS_DIR=/app/specs \
    MOCK_PROFILES_DIR=/app/profiles \
    MOCK_PORT=9105 \
    MOCK_PROFILE=default \
    MOCK_TICK_INTERVAL_SEC=1.0

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY main.py /app/main.py
COPY specs /app/specs
COPY profiles /app/profiles

EXPOSE 9105

ENTRYPOINT ["python", "/app/main.py"]
