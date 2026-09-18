#!/usr/bin/env bash
# Combined start command for the single Fly Machine running everything -
# see Dockerfile.fly and fly.toml. Fly volumes (like most PaaS disks) only
# attach to one Machine, and the API + vehicle watcher both need write
# access to the same SQLite database, so they run together here rather
# than as separate services.
set -e

# Backgrounded rather than awaited: scanning National Highways' full camera
# ID range takes minutes, far longer than Fly wants gunicorn to take to
# start listening. vehicle_watcher.py re-queries the camera list every
# cycle, so it naturally picks up cameras as this finishes populating them.
python src/sync_sources.py &

# Runs continuously in the background for the lifetime of the Machine.
python src/vehicle_watcher.py &

# gunicorn is the foreground process - Fly restarts the Machine if it exits.
# A single worker is plenty for this low-traffic API and leaves more of the
# Machine's memory for the watcher's OpenCV/ONNX inference.
exec gunicorn --chdir backend --bind "0.0.0.0:${PORT:-8080}" --workers 1 --timeout 30 app:app
