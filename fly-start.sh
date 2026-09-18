#!/usr/bin/env bash
# Start command for the single Fly Machine running everything - see
# Dockerfile.fly and fly.toml. The source sync and vehicle watcher run as
# background threads inside backend/app.py itself (RUN_BACKGROUND_TASKS=1,
# set in fly.toml) rather than as separate `python ...` processes: three
# separate processes each pay the full numpy/opencv/shapely/pyproj import
# cost again, which was enough to OOM-kill this Machine on its own.
set -e

# A single worker is plenty for this low-traffic API, and means the
# background threads above only ever start once (see backend/app.py).
exec gunicorn --chdir backend --bind "0.0.0.0:${PORT:-8080}" --workers 1 --timeout 30 app:app
