# The admin portal, for a demo deploy (Fly.io, Render, or any container host).
FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir ".[portal]"

# The portal writes demo state (proposals, approvals, the SQLite target) under here.
ENV FIRSTSYNC_STATE_DIR=/data
ENV FIRSTSYNC_PORTAL_PORT=8000
RUN mkdir -p /data

# The package is installed into site-packages, but the test orgs and the demo proposals
# live at the repo root (copied to /app). Point the lookups at their absolute paths so
# they resolve regardless of where the package itself sits.
ENV FIRSTSYNC_ORGS_DIR=/app/orgs
ENV FIRSTSYNC_DEMO_RESULTS_DIR=/app/results

EXPOSE 8000
CMD ["firstsync", "portal"]
