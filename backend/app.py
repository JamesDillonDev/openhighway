import sys
from dataclasses import asdict
from pathlib import Path

import requests
from flask import Flask, Response, jsonify
from flask_cors import CORS

# The scraper/config/db code lives in src/, not on the default import path.
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import db  # noqa: E402
from config import USER_AGENT, section  # noqa: E402

API_SETTINGS = section("api")

# Most sources' image URLs can be hotlinked directly by the browser (the
# default, bandwidth-cheap path - see get_cameras below). TrafficWatchNI's
# CCTV image host instead 403s any request without its own site as the
# Referer, so those images have to be fetched here and streamed back rather
# than loaded straight from the frontend.
IMAGE_PROXY_HEADERS = {
    "northern_ireland": {"Referer": "https://www.trafficwatchni.com/twni/cameras"},
}

app = Flask(__name__)
CORS(app, origins=[API_SETTINGS["cors_origin"]])

# Ensure the schema exists even if sync_sources.py hasn't been run yet.
_startup_conn = db.get_connection()
db.init_db(_startup_conn)
_startup_conn.close()


def _camera_dict(record):

    data = asdict(record)
    data["id"] = data.pop("master_id")

    if data["source"] in IMAGE_PROXY_HEADERS:
        data["image_url"] = f"/api/cameras/{data['id']}/image"

    return data


@app.get("/api/cameras")
def get_cameras():

    conn = db.get_connection()

    try:
        records = db.list_cameras(conn, active_only=True)
    finally:
        conn.close()

    # Only cameras with known coordinates can be placed on the map.
    # image_url points at the source provider directly - the frontend
    # renders it as-is rather than proxying images through this API.
    located = [
        _camera_dict(record) for record in records
        if record.latitude is not None and record.longitude is not None
    ]

    return jsonify(located)


@app.get("/api/cameras/<int:master_id>/history")
def get_camera_history(master_id):

    conn = db.get_connection()

    try:
        history = db.list_camera_images(conn, master_id)
    finally:
        conn.close()

    return jsonify(history)


@app.get("/api/cameras/<int:master_id>/image")
def get_camera_image(master_id):

    conn = db.get_connection()

    try:
        record = db.get_camera_by_master_id(conn, master_id)
    finally:
        conn.close()

    if record is None or not record.image_url:
        return "", 404

    headers = {"User-Agent": USER_AGENT, **IMAGE_PROXY_HEADERS.get(record.source, {})}

    try:
        upstream = requests.get(record.image_url, headers=headers, timeout=15)
        upstream.raise_for_status()
    except requests.RequestException:
        return "", 502

    return Response(upstream.content, content_type=upstream.headers.get("Content-Type", "image/jpeg"))


if __name__ == "__main__":
    app.run(
        host=API_SETTINGS["host"],
        port=API_SETTINGS["port"],
        debug=True
    )
