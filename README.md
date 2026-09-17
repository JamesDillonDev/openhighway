# openhighway

Scrapes National Highways CCTV camera metadata and images from
[public.highwaystrafficcameras.co.uk](https://public.highwaystrafficcameras.co.uk).

## Project structure

```
src/
  config.json          # single shared config: a section per script, plus global flags
  config.py             # loads config.json - scripts import settings from here
  master.py             # runs the pipeline steps below, in order or a chosen subset
  scrape_cameras.py      # scans camera IDs and builds national_highways_cameras.json
  camera_locations.py    # adds lat/lon coordinates using the National Highways Network Model API
  get_feeds.py           # downloads camera images listed in config/national_highways_cameras.json
  vehicle_watcher.py      # polls feeds every 30s and counts vehicles per camera with OpenCV
backend/
  app.py                 # Flask API serving camera data to the frontend
frontend/                 # React + Leaflet map UI
```

## Requirements

- Python 3
- `requests`
- `beautifulsoup4`
- `shapely`
- `pyproj`
- `opencv-python-headless`
- `numpy`
- `flask`, `flask-cors` (for `backend/app.py`)
- Node.js (for `frontend/`)

Install with:

```powershell
pip install requests beautifulsoup4 shapely pyproj opencv-python-headless numpy flask flask-cors
cd frontend; npm install
```

## Usage

### Run the full pipeline

```powershell
cd src
python .\master.py
```

Runs all three steps in order: `scrape_cameras` -> `camera_locations` ->
`get_feeds`. Each step runs as its own process, so a failure in one step
doesn't corrupt the others' state.

Run a subset (or a different order) with `--steps`:

```powershell
python .\master.py --steps get_feeds
python .\master.py --steps scrape_cameras,camera_locations
```

### Run a step individually

```powershell
cd src
python .\scrape_cameras.py
```

This scans camera IDs in the range set by `scrape_cameras.start_id`/`end_id`
in [config.json](src/config.json), checks each camera's image and page, and
writes the results to `national_highways_cameras.json`. Every camera whose
image exists is kept, tagged with an `available` flag (`true`/`false`) based
on whether the page text says something like "not available" or "unavailable".

```powershell
cd src
python .\camera_locations.py
```

Parses each camera's road/chainage/junction from its description, matches it
against the National Highways Network Model FeatureServer, and writes
`latitude`/`longitude` plus the matched link info back into
`national_highways_cameras.json` (a `.backup.json` copy is made first).

```powershell
cd src
python .\get_feeds.py
```

Reads `config/national_highways_cameras.json` and downloads each camera's
JPG into `config/camera_images/`.

### Watch traffic levels

```powershell
cd src
python .\vehicle_watcher.py
```

Runs forever (Ctrl+C to stop). Every `vehicle_watcher.interval_seconds`
(default 30s) it fetches each available camera's current image directly from
`image_url`, runs it through an OpenCV `MOG2` background subtractor to find
blobs that are moving relative to the static road/background, and writes the
count of blobs above `min_vehicle_area` as that camera's `vehicles` field in
`national_highways_cameras.json`. Each camera needs a few frames
(`warmup_frames`) before its background model settles, so `vehicles` stays
unset for a camera for its first few cycles. This is *not* one of
`master.py`'s default steps since it never exits - run it separately
(`python master.py --steps vehicle_watcher`) alongside the other steps.

### Run the map frontend

```powershell
cd backend
python .\app.py
```

```powershell
cd frontend
npm run dev
```

The Flask API (`backend/app.py`, port 5000) serves `/api/cameras` - each
camera's `image_url` points straight at National Highways, so the browser
loads feed images directly rather than through the backend. The React app
(`frontend/`, port 5173) plots every located camera on a map; marker colour
scales from blue (few/no vehicles) to red (heavy traffic, capped at
`MAX_VEHICLES_FOR_COLOR` in `frontend/src/App.jsx`) based on the `vehicles`
field, and grey for cameras with no data yet or marked unavailable. Clicking
a marker opens a panel with the live image and details. The frontend polls
`/api/cameras` every 30 seconds to stay in sync with `vehicle_watcher.py`.

## Configuration

All settings live in [src/config.json](src/config.json): a `global` section
shared by every script, plus one section per script/step.

| Section            | Setting           | Description                                    |
| ------------------- | ----------------- | ----------------------------------------------- |
| `global`            | `config_dir`      | Directory (relative to `src/`) for data/images   |
| `global`            | `camera_data_file`| Shared camera JSON filename                      |
| `global`            | `user_agent`      | User-Agent header sent with every request        |
| `master`            | `default_steps`   | Steps `master.py` runs when `--steps` is omitted |
| `scrape_cameras`    | `base_url`        | Base URL of the camera feed site                 |
| `scrape_cameras`    | `start_id`        | First camera ID to scan                          |
| `scrape_cameras`    | `end_id`          | Last camera ID to scan                           |
| `scrape_cameras`    | `workers`         | Concurrent threads used for scraping             |
| `get_feeds`         | `image_dir`       | Subdirectory (under `config_dir`) for images      |
| `get_feeds`         | `workers`         | Concurrent threads used for downloading           |
| `get_feeds`         | `timeout`         | Per-request timeout (seconds)                     |
| `camera_locations`  | `backup_file`     | Backup filename written before updating coords    |
| `camera_locations`  | `feature_server`  | National Highways Network Model FeatureServer URL |
| `camera_locations`  | `request_timeout` | Per-request timeout (seconds)                     |
| `camera_locations`  | `request_delay`   | Delay between FeatureServer requests (seconds)    |
| `vehicle_watcher`   | `interval_seconds`| How often to re-check every camera (seconds)      |
| `vehicle_watcher`   | `workers`         | Concurrent threads used for fetching/counting     |
| `vehicle_watcher`   | `request_timeout` | Per-request timeout (seconds)                     |
| `vehicle_watcher`   | `warmup_frames`   | Frames needed before a camera's count is trusted  |
| `vehicle_watcher`   | `min_vehicle_area`| Min. contour pixel area counted as one vehicle    |
| `api`               | `host` / `port`   | Where `backend/app.py` listens                    |
| `api`               | `cors_origin`     | Frontend origin allowed to call the API           |

`src/config.py` just loads `config.json` and exposes it to the scripts - edit
`config.json` to change any setting, not `config.py`.

## Troubleshooting

- **`NameResolutionError` / `getaddrinfo failed` on every request** — this is
  a DNS/network connectivity issue on your machine, not a bug in the script.
  Check your internet connection and try again.
