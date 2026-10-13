# Development Dockerfile for Backend (FastAPI + Uvicorn with hot-reload)
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install Git for the pinned Backtrader VCS dependency and curl for healthchecks.
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /opt/workspace/ai-for-investor/src/backend

# Install the audited lockfile, including the async PostgreSQL driver used by
# the default dev DATABASE_URL. Do not fall back to an incomplete extra set.
COPY config/requirements-dev.lock /tmp/requirements-dev.lock
RUN pip install --no-cache-dir -r /tmp/requirements-dev.lock

COPY src/backend /opt/workspace/ai-for-investor/src/backend
RUN pip install --no-cache-dir --no-deps -e .

# WeasyPrint is imported by the API router at startup and needs Pango/GObject.
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 && \
    rm -rf /var/lib/apt/lists/*

# Keep app log writes outside the source bind mount watched by uvicorn --reload.
ENV LOG_DIR=/var/log/ai-for-investor

# Create necessary directories
RUN mkdir -p \
    /opt/workspace/ai-for-investor/datas \
    /opt/workspace/ai-for-investor/workspace_units \
    /opt/workspace/ai-for-investor/src/backend/data \
    /opt/workspace/ai-for-investor/src/backend/logs \
    /var/log/ai-for-investor \
    /opt/workspace/ai-for-investor/strategies

# Copy entrypoint script
COPY docker/entrypoint-dev.sh /usr/local/bin/entrypoint-dev.sh
RUN chmod +x /usr/local/bin/entrypoint-dev.sh

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=180s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint-dev.sh"]
CMD ["uvicorn", "app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"]
