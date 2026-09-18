#!/usr/bin/env bash
# Combined start command for the Render "openhighway-api" web service.
#
# Render's persistent disks can only be attached to one service, and the
# backend API + vehicle watcher both need write access to the same SQLite
# database - so unlike docker-compose (separate backend/watcher services
# sharing a Docker volume), on Render they run together in this one process
# group, sharing this one service's disk.
set -e

# Populate/refresh the camera list on every deploy. A single source failing
# (e.g. Traffic Scotland when unconfigured) is non-fatal - see sync_sources.py.
python src/sync_sources.py || true

# Runs continuously in the background for the lifetime of the service.
python src/vehicle_watcher.py &

# gunicorn is the foreground process - Render considers the service "up"
# once it's bound to $PORT, and restarts the whole service if it exits.
exec gunicorn --chdir backend --bind "0.0.0.0:${PORT:-5000}" --workers 2 --timeout 30 app:app
