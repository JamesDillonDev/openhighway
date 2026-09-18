# OpenHighways

Collects public traffic CCTV camera metadata and live images from across the
UK, counts vehicles in each feed with a computer-vision model, and shows it
all on a live map.

## Sources

Each source is a self-contained module under [`src/sources/`](src/sources)
that knows how to discover its own cameras, locate them, and fetch their
images - the rest of the system never has provider-specific logic in it.

| Source              | Coverage                                  | Status                                                          |
| -------------------- | ------------------------------------------ | ---------------------------------------------------------------- |
| `national_highways`  | England strategic road network (M/A roads) | Active - public, unauthenticated                                  |
| `tfl`                | Greater London (JamCams)                   | Active - public, unauthenticated (optional `TFL_APP_KEY` for a higher rate limit) |
| `traffic_wales`      | Wales trunk road network                   | Active - public, unauthenticated (coordinates approximated via OpenStreetMap geocoding) |
| `northern_ireland`   | Northern Ireland trunk road network        | Active - public, unauthenticated (TrafficWatchNI; coordinates approximated via OpenStreetMap geocoding) |
| `traffic_scotland`   | Scotland trunk road network                | Not yet active - Traffic Scotland's camera feed requires approved-subscriber FTP access (see `src/sources/traffic_scotland.py`) |

## Project structure

```
src/
  config.json            # single shared config: a section per script/source, plus global flags
  config.py               # loads config.json - modules import settings from here
  db.py                    # SQLite storage - the primary source of truth for camera data
  models.py                # typed Camera/SourceCamera data models
  pipeline.py               # provider-agnostic master pipeline: sources -> database
  sync_sources.py            # CLI entry point - runs the pipeline for one or all sources
  vehicle_watcher.py          # polls camera feeds and counts vehicles with a CV model
  vehicle_detector.py           # the single-frame vehicle detector (YOLOX ONNX model)
  sources/
    source.py                   # the Source base class every provider implements
    national_highways.py         # National Highways
    tfl.py                        # Transport for London
    traffic_wales.py               # Traffic Wales
    northern_ireland.py             # TrafficWatchNI (Northern Ireland)
    traffic_scotland.py             # Traffic Scotland (stub pending subscriber access)
backend/
  app.py                 # Flask API serving camera data (from the database) to the frontend
frontend/                 # React + Leaflet map UI
```

## Requirements

- Python 3
- `requests`, `beautifulsoup4` (HTML-scraping sources)
- `shapely`, `pyproj` (National Highways road-geometry matching)
- `opencv-python`, `numpy` (vehicle detection)
- `flask`, `flask-cors` (`backend/app.py`)
- Node.js (`frontend/`)

Install with:

```powershell
pip install requests beautifulsoup4 shapely pyproj opencv-python numpy flask flask-cors
cd frontend; npm install
```

## Usage

The quickest way to bring everything up is [`start-dev.ps1`](start-dev.ps1)
from the repo root, which syncs sources into the database then launches the
backend, vehicle watcher and frontend each in their own window:

```powershell
.\start-dev.ps1
```

Flags: `-SkipSync` (skip the source sync - use if the database is already
populated), `-SkipWatcher`, `-SkipInstall` (skip `npm install`).

### Sync camera sources into the database

```powershell
cd src
python .\sync_sources.py
python .\sync_sources.py --sources tfl,traffic_wales
```

Runs every configured [source](#sources) (or just the ones named), matching
cameras on `(source, internal_id)`: new cameras get a permanent `master_id`,
existing ones are updated in place, and cameras no longer reported by a
source are marked `active = 0` rather than deleted - a `master_id` is never
reused. A failure in one source (e.g. Traffic Scotland, until it's
configured) never stops the others.

### Watch traffic levels

```powershell
cd src
python .\vehicle_watcher.py
```

Runs forever (Ctrl+C to stop). Every `vehicle_watcher.interval_seconds`
(default 60s) it fetches every active camera's current image and runs it
through a YOLOX object-detection model (`vehicle_detector.py`) to count
cars/motorcycles/buses/trucks directly in that single frame - no frame
history or per-camera warmup needed, so it works even on feeds that rarely
refresh. The count is written to that camera's `vehicles` field, and a
timestamped history point is kept (capped at `max_history_points`) for the
frontend's traffic-history graph. Only the latest snapshot per camera is
kept on disk (`config/camera_images/{master_id}.jpg`), not a full archive.

### Run the map frontend

```powershell
cd backend
python .\app.py
```

```powershell
cd frontend
npm run dev
```

The Flask API (`backend/app.py`, port 5000) serves `/api/cameras` and
`/api/cameras/<id>/history` straight from the SQLite database - each
camera's `image_url` points at its source directly, so the browser loads
feed images itself rather than through the backend. The React app
(`frontend/`, port 5173) plots every located camera on a map, colour-scaled
from blue (few/no vehicles) to red (heavy traffic); a per-source checkbox
panel lets you show/hide cameras by provider. Clicking a marker opens a
panel with the live image (click it to enlarge) and traffic history. The
frontend polls `/api/cameras` every 30 seconds and refreshes open camera
images every 15 seconds.

## Database

[`src/db.py`](src/db.py) is the primary source of truth (SQLite,
`src/config/openhighway.sqlite3`) - not the old JSON files. Two tables:

- **`cameras`** - one row per camera, keyed by `master_id` (a permanent,
  auto-incrementing OpenHighways ID that's never reused) plus
  `(source, internal_id)` for matching a provider's own camera ID.
  `active` tracks whether the last sync still saw this camera; `vehicles`
  caches its latest count.
- **`camera_images`** - a timestamped `vehicle_count` history per camera,
  pruned to `max_history_points`.

`db.export_to_json()` can dump the database to JSON for debugging/backups,
but normal operation never reads or writes JSON directly.

## Adding a new source

1. Create `sources/<name>.py` with a class inheriting from `Source`
   (see [`sources/source.py`](src/sources/source.py) for the interface -
   `discover_cameras`, `get_camera`, `get_latest_image`).
2. Register it in [`sources/__init__.py`](src/sources/__init__.py)'s
   `AVAILABLE_SOURCES`.
3. Add a `sources.<name>` section to `config.json` for anything it needs
   (base URL, timeouts, etc.) - secrets like API keys/passwords should come
   from environment variables instead, never config.json (see `tfl.py`'s
   `TFL_APP_KEY` or `traffic_scotland.py`'s FTP credentials for examples).

The database, master ID assignment and pipeline never need to change.

## Configuration

All settings live in [src/config.json](src/config.json): a `global` section,
one section per source under `sources`, plus `vehicle_watcher` and `api`.

| Section                          | Setting              | Description                                        |
| --------------------------------- | ---------------------- | ----------------------------------------------------- |
| `global`                          | `config_dir`          | Directory (relative to `src/`) for the database/images |
| `global`                          | `database_file`       | SQLite filename                                        |
| `global`                          | `user_agent`          | User-Agent header sent with every request              |
| `master`                          | `default_steps`       | Default step(s) run when none are specified            |
| `sources.national_highways`       | `base_url`            | Base URL of the camera feed site                       |
| `sources.national_highways`       | `start_id` / `end_id` | Camera ID range to scan                                |
| `sources.national_highways`       | `workers`             | Concurrent threads used for scraping                   |
| `sources.national_highways`       | `feature_server`      | National Highways Network Model FeatureServer URL      |
| `sources.tfl`                     | `base_url`            | TfL Unified API base URL                               |
| `sources.traffic_wales`           | `base_url`/`index_path` | Road-cameras index page                              |
| `sources.traffic_wales`           | `geocode_base_url`    | Nominatim endpoint used to approximate coordinates     |
| `sources.traffic_wales`           | `geocode_delay_seconds` | Delay between geocoding requests (rate-limit friendly) |
| `sources.traffic_scotland`        | `ftp_host`/`ftp_directory` | FTP feed location (credentials via env vars)       |
| `vehicle_watcher`                 | `interval_seconds`    | How often to re-check every camera (seconds)           |
| `vehicle_watcher`                 | `workers`             | Concurrent threads used for fetching images             |
| `vehicle_watcher`                 | `input_size`          | Detector input resolution (smaller = faster, less accurate) |
| `vehicle_watcher`                 | `confidence_threshold`/`nms_threshold` | Detection thresholds                  |
| `vehicle_watcher`                 | `max_history_points`  | History points kept per camera                         |
| `api`                              | `host` / `port`       | Where `backend/app.py` listens                         |
| `api`                              | `cors_origin`         | Frontend origin allowed to call the API                |

`src/config.py` just loads `config.json` and exposes it to the modules - edit
`config.json` to change any setting, not `config.py`.

## Deployment

### Docker Compose (self-hosted)

`docker-compose.yml` runs four services from the same [`Dockerfile`](Dockerfile)/
[`frontend/Dockerfile`](frontend/Dockerfile): `backend`, `watcher` and
`frontend`, plus a one-off `sync` service (`docker compose run --rm sync`).
`backend` and `watcher` share one Docker volume (`openhighway-data`) mounted
at `/app/src/config`, so they both read/write the same SQLite database.

```powershell
docker compose up -d --build
```

### Render

[`render.yaml`](render.yaml) defines a Render [Blueprint](https://render.com/docs/blueprint-spec)
with two services:

- **`openhighway-api`** - a Docker-based web service running
  [`render-start.sh`](render-start.sh), which syncs sources, starts the
  vehicle watcher in the background, then runs the Flask API under
  gunicorn in the foreground. It has a 1 GB persistent disk mounted at
  `/app/src/config` for the SQLite database, camera image cache and
  geocode caches.

  Render only allows a persistent disk to be attached to *one* service, and
  the API and watcher both need to read/write the same database - that's
  why they run together in one service here, unlike the two separate
  `backend`/`watcher` services in docker-compose. A disk also requires a
  paid compute plan (the `free` plan supports neither disks nor an
  always-on process for the watcher).

- **`openhighway-frontend`** - a free static site built from `frontend/`,
  with a rewrite rule proxying `/api/*` to `openhighway-api`'s URL so the
  browser only ever talks to one origin (no CORS needed for normal use).

To deploy: push this repo to GitHub, then in the [Render Dashboard](https://dashboard.render.com)
choose **New > Blueprint** and point it at the repo. After both services are
created:

1. Confirm `openhighway-api`'s actual `onrender.com` URL (Render may assign
   a different subdomain if `openhighway-api`/`openhighway-frontend` are
   already taken) and update the `CORS_ORIGIN` env var on `openhighway-api`
   and the rewrite `destination` in `render.yaml` (then redeploy) if so.
2. Optionally set `TFL_APP_KEY` and/or the Traffic Scotland FTP credentials
   as env vars on `openhighway-api` - the Blueprint prompts for these
   during setup since they're secrets (`sync: false`).

## Troubleshooting

- **`NameResolutionError` / `getaddrinfo failed` on every request** — this is
  a DNS/network connectivity issue on your machine, not a bug in the script.
  Check your internet connection and try again.
