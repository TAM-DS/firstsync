# The admin portal, for a demo deploy (Fly.io, Render, or any container host).
FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir ".[portal]"

# The portal writes demo state (proposals, approvals, the SQLite target) under here.
ENV FIRSTSYNC_STATE_DIR=/data
ENV FIRSTSYNC_PORTAL_PORT=8000
RUN mkdir -p /data

EXPOSE 8000
CMD ["firstsync", "portal"]
