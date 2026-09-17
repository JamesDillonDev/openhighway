# openhighway

Scrapes National Highways CCTV camera metadata and images from
[public.highwaystrafficcameras.co.uk](https://public.highwaystrafficcameras.co.uk).

## Project structure

```
src/
  config.py           # shared settings (base URL, ID range, worker count, etc.)
  scrape_cameras.py    # scans camera IDs and builds national_highways_cameras.json
  get_feeds.py         # downloads camera images listed in config/national_highways_cameras.json
```

## Requirements

- Python 3
- `requests`
- `beautifulsoup4`

Install with:

```powershell
pip install requests beautifulsoup4
```

## Usage

### 1. Scrape camera metadata

```powershell
cd src
python .\scrape_cameras.py
```

This scans camera IDs in the range set by `START_ID`/`END_ID` in
[config.py](src/config.py), checks each camera's image and page, and writes
the results to `national_highways_cameras.json`. Cameras with the description
"Camera not available" are skipped.

### 2. Download camera images

```powershell
cd src
python .\get_feeds.py
```

Reads `config/national_highways_cameras.json` and downloads each camera's
JPG into `config/camera_images/`.

## Configuration

Settings in [src/config.py](src/config.py):

| Setting      | Description                                  |
| ------------ | --------------------------------------------- |
| `BASE_URL`   | Base URL of the camera feed site              |
| `OUTPUT_FILE`| Output JSON filename for scraped camera data  |
| `START_ID`   | First camera ID to scan                       |
| `END_ID`     | Last camera ID to scan                        |
| `WORKERS`    | Number of concurrent threads used for scraping|
| `USER_AGENT` | User-Agent header sent with each request      |

## Troubleshooting

- **`NameResolutionError` / `getaddrinfo failed` on every request** — this is
  a DNS/network connectivity issue on your machine, not a bug in the script.
  Check your internet connection and try again.
