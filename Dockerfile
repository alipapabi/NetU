FROM python:3.12-slim

WORKDIR /app

# 依赖单独拷贝，利用 Docker 层缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 运行时目录（可通过 -v 挂载覆盖）
RUN mkdir -p /app/down /app/config

ENV NETU_HOST=0.0.0.0 \
    NETU_PORT=8899 \
    NETU_DOWN_DIR=/app/down \
    NETU_CONFIG=/app/config/.passwords.yaml \
    PYTHONUNBUFFERED=1

EXPOSE 8899

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8899/login', timeout=4).status==200 else 1)"

CMD ["python", "app.py"]
