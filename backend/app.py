import sys
from dataclasses import asdict
from pathlib import Path

from flask import Flask, jsonify
from flask_cors import CORS

# The scraper/config/db code lives in src/, not on the default import path.
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import db  # noqa: E402
from config import section  # noqa: E402

API_SETTINGS = section("api")

app = Flask(__name__)
CORS(app, origins=[API_SETTINGS["cors_origin"]])

# Ensure the schema exists even if sync_sources.py hasn't been run yet.
_startup_conn = db.get_connection()
db.init_db(_startup_conn)
_startup_conn.close()


def _camera_dict(record):

    data = asdict(record)
    data["id"] = data.pop("master_id")

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


if __name__ == "__main__":
    app.run(
        host=API_SETTINGS["host"],
        port=API_SETTINGS["port"],
        debug=True
    )
