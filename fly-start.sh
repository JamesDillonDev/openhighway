#!/usr/bin/env bash
# Combined start command for the single Fly Machine running everything -
# see Dockerfile.fly and fly.toml. Fly volumes (like most PaaS disks) only
# attach to one Machine, and the API + vehicle watcher both need write
# access to the same SQLite database, so they run together here rather
# than as separate services.
set -e

# Populate/refresh the camera list on every deploy. A single source failing
# (e.g. Traffic Scotland when unconfigured) is non-fatal - see sync_sources.py.
python src/sync_sources.py || true

# Runs continuously in the background for the lifetime of the Machine.
python src/vehicle_watcher.py &

# gunicorn is the foreground process - Fly restarts the Machine if it exits.
exec gunicorn --chdir backend --bind "0.0.0.0:${PORT:-8080}" --workers 2 --timeout 30 app:app
