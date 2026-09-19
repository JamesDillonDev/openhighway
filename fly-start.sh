#!/usr/bin/env bash
# Start command for the single Fly Machine running everything - see
# Dockerfile.fly and fly.toml. The source sync and vehicle watcher run as
# background threads inside backend/app.py itself (RUN_BACKGROUND_TASKS=1,
# set in fly.toml) rather than as separate `python ...` processes: three
# separate processes each pay the full numpy/opencv/shapely/pyproj import
# cost again, which was enough to OOM-kill this Machine on its own.
set -e

# A single worker keeps the background threads above starting only once
# (see backend/app.py), but gunicorn's default "sync" worker class handles
# only one HTTP request at a time - with everything else queued behind it,
# a single slow request (e.g. the NI image proxy's extra round-trip) stalls
# every other request too. gthread lets this one worker serve several
# requests concurrently via threads instead.
exec gunicorn --chdir backend --bind "0.0.0.0:${PORT:-8080}" --workers 1 --worker-class gthread --threads 8 --timeout 30 app:app
