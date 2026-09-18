"""Traffic Wales source: discovers CCTV cameras from traffic.wales, which
lists cameras grouped by road on public HTML pages, each with a direct,
unauthenticated image URL - no API key or subscription required.

Genuinely public, unlike Traffic Scotland's subscriber-gated FTP feed, and
structured differently again from National Highways (no ID range to scan -
traffic.wales already groups cameras by road) and TfL (no JSON API - plain
HTML with <img> tags).

traffic.wales's own map plots cameras via a licensed third-party widget
(Elgin) authenticated with the site's own embed credentials - reusing those
isn't something we can do, so coordinates come from geocoding each camera's
name/road with OpenStreetMap's free Nominatim search instead (approximate,
not the exact camera pole position, but enough to place it on the map).
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import CONFIG_DIR, USER_AGENT, section
from models import SourceCamera

from .source import Source


class TrafficWalesSource(Source):

    name = "traffic_wales"

    IMAGE_ID_RE = re.compile(r"camera(\d+)\.jpg", re.IGNORECASE)
    DIRECTION_RE = re.compile(r"\((\w+bound)\)", re.IGNORECASE)
    ROAD_LINK_RE = re.compile(r"^/(cctv-cameras|taxonomy/term)/")

    def __init__(self) -> None:

        super().__init__()

        settings = section("sources")["traffic_wales"]

        self.base_url = settings["base_url"]
        self.index_path = settings["index_path"]
        self.workers = settings.get("workers", 8)
        self.request_timeout = settings.get("request_timeout", 20)

        self.geocode_base_url = settings["geocode_base_url"]
        self.geocode_delay = settings.get("geocode_delay_seconds", 1.0)
        self._geocode_cache_path = CONFIG_DIR / "traffic_wales_geocode_cache.json"
        self._geocode_cache = self._load_geocode_cache()

        self.session = self._build_session(USER_AGENT, workers=self.workers)

    def metadata(self) -> dict:
        return {
            "name": self.name,
            "display_name": "Traffic Wales",
            "coverage": "Wales trunk road network",
        }

    # ------------------------------------------------------------------
    # Source interface
    # ------------------------------------------------------------------

    def discover_cameras(self) -> list[SourceCamera]:
        return list(self._scan().values())

    def get_camera(self, internal_id: str) -> Optional[SourceCamera]:
        return self._scan().get(internal_id)

    def get_latest_image(self, internal_id: str, image_url: Optional[str] = None) -> Optional[bytes]:

        # Most cameras use a plain camera{id}.jpg URL, but some are prefixed
        # with their road code (e.g. a40camera7197.jpg) - not deterministic
        # enough to guess, so without a cached URL this needs a re-scan.
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
    # Discovery: road index page -> one page per road -> camera <img> tags
    # ------------------------------------------------------------------


    def _road_pages(self) -> list[tuple[str, str]]:
        """[(road_label, road_page_url), ...] from the road-cameras index."""

        url = urljoin(self.base_url, self.index_path)
        response = self.session.get(url, timeout=self.request_timeout)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        return [
            (a.get_text(strip=True), urljoin(self.base_url, a["href"]))
            for a in soup.find_all("a", href=True)
            if self.ROAD_LINK_RE.match(a["href"])
        ]

    def _cameras_on_page(self, road_label: str, page_url: str) -> list[dict]:

        try:
            response = self.session.get(page_url, timeout=self.request_timeout)
            response.raise_for_status()
        except requests.RequestException as error:
            self.logger.warning("Failed to fetch road page %s: %s", page_url, error)
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        cameras = []

        for img in soup.find_all("img"):

            src = img.get("src") or ""
            match = self.IMAGE_ID_RE.search(src)

            if not match:
                continue

            cameras.append({
                "id": match.group(1),
                "image_url": src,
                "alt": (img.get("alt") or "").strip(),
                "road": road_label,
            })

        return cameras

    def _scan(self) -> dict[str, SourceCamera]:

        cameras: dict[str, SourceCamera] = {}

        with ThreadPoolExecutor(max_workers=self.workers) as executor:

            futures = [
                executor.submit(self._cameras_on_page, road_label, page_url)
                for road_label, page_url in self._road_pages()
            ]

            for future in as_completed(futures):

                for raw_camera in future.result():

                    # A camera near a junction can appear on more than one
                    # road's page - first one found wins, it's still the
                    # same physical camera.
                    if raw_camera["id"] not in cameras:
                        cameras[raw_camera["id"]] = self._normalise(raw_camera)

        # Geocoding hits an external, rate-limited service - do it as a
        # separate sequential pass rather than inside the concurrent scan
        # above, and only for cameras not already cached from a past run.
        for camera in cameras.values():
            camera.latitude, camera.longitude = self._geocode(camera.name, camera.road)

        self._save_geocode_cache()

        return cameras

    def _normalise(self, raw_camera: dict) -> SourceCamera:

        alt = raw_camera["alt"]

        direction_match = self.DIRECTION_RE.search(alt)
        direction = direction_match.group(1).capitalize() if direction_match else None

        # "J24 Coldra (Eastbound) Camera" -> "J24 Coldra"
        name = self.DIRECTION_RE.sub("", alt)
        name = re.sub(r"\s*Camera\s*$", "", name, flags=re.IGNORECASE).strip()

        return SourceCamera(
            internal_id=raw_camera["id"],
            name=name or None,
            latitude=None,
            longitude=None,
            road=raw_camera["road"],
            direction=direction,
            image_url=raw_camera["image_url"],
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
        """Strip junction codes/road-prefixes that hurt Nominatim matches
        without adding any real place information (e.g. "A449 - Abernant
        Junction North" -> "Abernant")."""

        if not name:
            return None

        cleaned = re.sub(r"^[A-Z]\d+[A-Z]?\s*-\s*", "", name)
        cleaned = re.sub(r"^J\d+[A-Z]?\s+", "", cleaned)
        cleaned = re.sub(r"\b(Junction|Jct)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(North|South|East|West)\b\s*$", "", cleaned, flags=re.IGNORECASE)

        return cleaned.strip() or None

    def _geocode(self, name: Optional[str], road: Optional[str]) -> tuple[Optional[float], Optional[float]]:

        # Try progressively broader/cleaner queries - a camera's specific
        # label (e.g. "Coldra East") often isn't itself a place Nominatim
        # knows, but the underlying place name or road usually is. Skips
        # the combined "name, road" form entirely - in practice Nominatim's
        # structured comma-parsing almost never matched it, so it was just
        # a wasted rate-limited request on nearly every camera.
        cleaned_name = self._clean_name(name)

        attempts = []

        if name:
            attempts.append(f"{name}, Wales, UK")
        if cleaned_name and cleaned_name != name:
            attempts.append(f"{cleaned_name}, Wales, UK")
        if road:
            attempts.append(f"{road}, Wales, UK")

        for query in attempts:

            if query in self._geocode_cache:
                cached = self._geocode_cache[query]

                if cached is None:
                    continue

                return cached["lat"], cached["lon"]

            lat, lon = self._query_nominatim(query)
            self._geocode_cache[query] = {"lat": lat, "lon": lon} if lat is not None else None
            # Persist as we go - geocoding hundreds of cameras at ~1
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
