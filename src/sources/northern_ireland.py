"""Northern Ireland source: discovers CCTV cameras from trafficwatchni.com,
the Department for Infrastructure's public traffic camera site.

Simpler than Traffic Wales: a single HTML page (grouped by region in the UI,
but all regions are present in one response) lists every camera with both
its display name and a direct, unauthenticated image URL already embedded -
no per-camera page fetch, ID range scan, or road-geometry lookup needed.

TrafficWatchNI's own interactive map plots these same cameras with real
coordinates, but that data comes from a CSRF-token-gated AJAX endpoint tied
to a browser session - not worth reverse engineering for what the public
HTML listing already gives us. Coordinates are instead approximated the
same way Traffic Wales's are: geocoding each camera's name/region with
OpenStreetMap's free Nominatim search (cached to disk).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import CONFIG_DIR, USER_AGENT, section
from models import SourceCamera

from .source import Source


class NorthernIrelandSource(Source):

    name = "northern_ireland"

    ROAD_RE = re.compile(r"\b((?:M|A|B)\d+(?:\(M\))?)\b", re.IGNORECASE)
    TITLE_PREFIX_RE = re.compile(r"^View camera\s*:\s*", re.IGNORECASE)
    ONCLICK_RE = re.compile(r'addToPreview\(\d+,\s*"([^"]+)",\s*"\d+",\s*"([^"]+)"')

    def __init__(self) -> None:

        super().__init__()

        settings = section("sources")["northern_ireland"]

        self.base_url = settings["base_url"]
        self.index_path = settings["index_path"]
        self.request_timeout = settings.get("request_timeout", 20)

        self.geocode_base_url = settings["geocode_base_url"]
        self.geocode_delay = settings.get("geocode_delay_seconds", 1.0)
        self._geocode_cache_path = CONFIG_DIR / "northern_ireland_geocode_cache.json"
        self._geocode_cache = self._load_geocode_cache()

        self.session = self._build_session(USER_AGENT, workers=1)

        # cctv.trafficwatchni.com 403s any image request without its own
        # site as the Referer - unlike every other source, this isn't
        # optional metadata, so it's set once here rather than per-request.
        self.session.headers.update({"Referer": urljoin(self.base_url, self.index_path)})

    def metadata(self) -> dict:
        return {
            "name": self.name,
            "display_name": "TrafficWatchNI",
            "coverage": "Northern Ireland trunk road network",
        }

    # ------------------------------------------------------------------
    # Source interface
    # ------------------------------------------------------------------

    def discover_cameras(self) -> list[SourceCamera]:
        return list(self._scan().values())

    def get_camera(self, internal_id: str) -> Optional[SourceCamera]:
        return self._scan().get(internal_id)

    def get_latest_image(self, internal_id: str, image_url: Optional[str] = None) -> Optional[bytes]:

        # Image URLs are stable (plain numeric filenames), so a cached one
        # skips re-fetching and re-parsing the whole camera listing.
        if not image_url:
            camera = self.get_camera(internal_id)
            image_url = camera.image_url if camera else None

        if not image_url:
            return None

        try:
            response = self.session.get(image_url, timeout=self.request_timeout)
            response.raise_for_status()
            return response.content

        except requests.RequestException as error:
            self.logger.warning("Failed to fetch image for %s: %s", internal_id, error)
            return None

    # ------------------------------------------------------------------
    # Discovery: one HTML listing page already has every camera + image URL
    # ------------------------------------------------------------------

    def _region_by_group(self, soup: BeautifulSoup) -> dict[str, str]:
        """{"group2": "Greater Belfast", ...} from the region filter dropdown."""

        regions = {}

        for checkbox in soup.select(".dropdown-menu .form-check-input"):

            group_id = checkbox.get("data-groupid")
            label = checkbox.find_parent("label")

            if group_id and label:
                regions[group_id] = label.get_text(strip=True)

        return regions

    def _parse_fragment(self, fragment, region_by_group: dict[str, str]) -> Optional[dict]:

        camera_id = fragment.get("data-cctv-id")
        link = fragment.select_one("#cameraLink")
        button = fragment.select_one('button[onclick^="addToPreview"]')

        if not camera_id or not link or not button:
            return None

        match = self.ONCLICK_RE.search(button.get("onclick", ""))

        if not match:
            return None

        # The onclick attribute's JS string literal escapes its slashes
        # (e.g. "https:\/\/cctv.trafficwatchni.com") - unescape before use.
        image_base = match.group(1).replace("\\/", "/")
        image_file = match.group(2).replace("\\/", "/")
        name = self.TITLE_PREFIX_RE.sub("", link.get("title", "")).strip()

        group = fragment.find_parent(class_="camera-group-container")
        region = region_by_group.get(group.get("id")) if group else None

        return {
            "id": camera_id,
            "name": name or None,
            "image_url": f"{image_base}/{image_file}",
            "region": region,
        }

    def _scan(self) -> dict[str, SourceCamera]:

        url = urljoin(self.base_url, self.index_path)
        response = self.session.get(url, timeout=self.request_timeout)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        region_by_group = self._region_by_group(soup)

        cameras: dict[str, SourceCamera] = {}

        for fragment in soup.select(".cameraFragment"):

            raw_camera = self._parse_fragment(fragment, region_by_group)

            if raw_camera:
                cameras[raw_camera["id"]] = self._normalise(raw_camera)

        # Geocoding hits an external, rate-limited service - do it as a
        # separate sequential pass, and only for cameras not already
        # cached from a past run.
        for camera in cameras.values():
            camera.latitude, camera.longitude = self._geocode(camera.name, camera.extra.get("region"))

        self._save_geocode_cache()

        return cameras

    def _normalise(self, raw_camera: dict) -> SourceCamera:

        road_match = self.ROAD_RE.search(raw_camera["name"] or "")
        road = road_match.group(1).upper() if road_match else None

        return SourceCamera(
            internal_id=raw_camera["id"],
            name=raw_camera["name"],
            latitude=None,
            longitude=None,
            road=road,
            direction=None,
            image_url=raw_camera["image_url"],
            extra={"region": raw_camera["region"]},
        )

    # ------------------------------------------------------------------
    # Geocoding: approximate coordinates via OpenStreetMap's free Nominatim
    # search, cached to disk since it's rate-limited to ~1 request/second.
    # ------------------------------------------------------------------

    def _load_geocode_cache(self) -> dict:

        if not self._geocode_cache_path.exists():
            return {}

        try:
            return json.loads(self._geocode_cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_geocode_cache(self) -> None:

        self._geocode_cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._geocode_cache_path.write_text(
            json.dumps(self._geocode_cache, indent=2), encoding="utf-8"
        )

    def _clean_name(self, name: Optional[str]) -> Optional[str]:
        """Strip road-prefixes/junction codes that hurt Nominatim matches
        without adding any real place information (e.g. "A2 - Tillysburn"
        -> "Tillysburn", "M1 Stockmans Lane - J2" -> "Stockmans Lane")."""

        if not name:
            return None

        cleaned = re.sub(r"^[A-Z]\d+(?:\([A-Z]\))?\s*-\s*", "", name)
        cleaned = re.sub(r"\s*-\s*J\d+[A-Z]?$", "", cleaned)
        cleaned = re.sub(r"\b(Junction|Jct)\b", "", cleaned, flags=re.IGNORECASE)

        return cleaned.strip() or None

    def _geocode(self, name: Optional[str], region: Optional[str]) -> tuple[Optional[float], Optional[float]]:

        cleaned_name = self._clean_name(name)

        attempts = []

        if name:
            attempts.append(f"{name}, Northern Ireland, UK")
        if cleaned_name and cleaned_name != name:
            attempts.append(f"{cleaned_name}, Northern Ireland, UK")
        if cleaned_name and region:
            attempts.append(f"{cleaned_name}, {region}, Northern Ireland, UK")

        for query in attempts:

            if query in self._geocode_cache:
                cached = self._geocode_cache[query]

                if cached is None:
                    continue

                return cached["lat"], cached["lon"]

            lat, lon = self._query_nominatim(query)
            self._geocode_cache[query] = {"lat": lat, "lon": lon} if lat is not None else None
            # Persist as we go - geocoding a hundred-plus cameras at ~1
            # req/sec takes minutes, and an interrupted run shouldn't have
            # to redo the lookups it already paid for.
            self._save_geocode_cache()

            if lat is not None:
                return lat, lon

        return None, None

    def _query_nominatim(self, query: str) -> tuple[Optional[float], Optional[float]]:

        try:
            # Nominatim's usage policy caps unauthenticated use at ~1
            # request/second - only hit the network for a real cache miss.
            time.sleep(self.geocode_delay)

            response = self.session.get(
                self.geocode_base_url,
                params={"q": query, "format": "json", "limit": 1},
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            results = response.json()

        except requests.RequestException as error:
            self.logger.warning("Geocoding failed for '%s': %s", query, error)
            return None, None

        if not results:
            return None, None

        return float(results[0]["lat"]), float(results[0]["lon"])
