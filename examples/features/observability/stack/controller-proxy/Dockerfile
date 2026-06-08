# controller-metrics-proxy
# 把 pyMotor Controller 的 JSON 包装指标 (/observability/metrics) 解包为原生
# Prometheus 文本，供 Prometheus 抓取。仅依赖 Python 标准库。
FROM python:3.12-slim

LABEL org.opencontainers.image.title="controller-metrics-proxy" \
      org.opencontainers.image.description="Unwraps pyMotor Controller JSON metrics into Prometheus exposition format."

WORKDIR /app
COPY main.py /app/main.py

ENV CONTROLLER_METRICS_URL="http://host.docker.internal:1027/observability/metrics" \
    PROXY_PORT="9106" \
    CONTROLLER_TIMEOUT="5" \
    JSON_DATA_KEY="data" \
    INSECURE_SKIP_VERIFY="true" \
    PROXY_LOG_LEVEL="INFO"

EXPOSE 9106

HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PROXY_PORT','9106')+'/healthz', timeout=3)" || exit 1

ENTRYPOINT ["python", "/app/main.py"]
