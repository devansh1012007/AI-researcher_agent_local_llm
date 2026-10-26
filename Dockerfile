# Minimal single-app image: API + MCP + scheduler in ONE process (spec #151).
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd -m gar

ENV GAR_STORAGE__DATA_DIR=/data
USER gar
RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8000

CMD ["research", "serve", "--host", "0.0.0.0", "--port", "8000"]
