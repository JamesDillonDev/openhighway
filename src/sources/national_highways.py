"""National Highways source: discovers CCTV cameras from
public.highwaystrafficcameras.co.uk and locates them using the National
Highways Network Model FeatureServer.

All National Highways-specific logic (ID scanning, HTML scraping, road
geometry matching) lives in this file - nothing about it leaks into the
master pipeline.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform

from config import USER_AGENT, section
from models import SourceCamera

from .source import Source


class NationalHighwaysSource(Source):

    name = "national_highways"

    DESCRIPTION_RE = re.compile(r"Camera:\s*(\d+)\s*-\s*(.*?)(?:Refresh|$)", re.IGNORECASE)
    CARRIAGEWAY_RE = re.compile(r"carriageway closest to the camera is\s+(.*?)(?:\.|$)", re.IGNORECASE)
    UNAVAILABLE_RE = re.compile(r"\b(not\s+available|unavailable)\b", re.IGNORECASE)
    ROAD_RE = re.compile(r"\b((?:M|A)\d+(?:\(M\))?[A-Z]?)\b")
    CHAINAGE_RE = re.compile(r"\b(\d+/\d+[A-Z]?)\b")
    JUNCTION_RE = re.compile(r"\bJ(\d+[A-Z]?(?:-\d+[A-Z]?)?)\b")
    NON_ALNUM_RE = re.compile(r"[^A-Z0-9]")
    WORD_RE = re.compile(r"[A-Z0-9]+")

    def __init__(self) -> None:

        super().__init__()

        settings = section("sources")["national_highways"]

        self.base_url = settings["base_url"]
        self.start_id = settings["start_id"]
        self.end_id = settings["end_id"]
        self.workers = settings["workers"]
        self.feature_server = settings["feature_server"]
        self.request_timeout = settings["request_timeout"]
        self.request_delay = settings["request_delay"]

        self.session = self._build_session(USER_AGENT, workers=self.workers)

        # National Highways Network Model is EPSG:3857 - we want plain GPS coordinates.
        self._transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

    def metadata(self) -> dict:
        return {
            "name": self.name,
            "display_name": "National Highways",
            "coverage": "England strategic road network (motorways & A-roads)",
            "camera_id_range": [self.start_id, self.end_id],
        }

    # ------------------------------------------------------------------
    # Source interface
    # ------------------------------------------------------------------

    def discover_cameras(self) -> list[SourceCamera]:

        raw_cameras = self._scan_camera_ids()

        # Shared across cameras so 200 cameras on the M25 only cost one
        # FeatureServer query for "M25", not 200.
        road_cache: dict[str, list[dict]] = {}

        return [self._normalise(raw_camera, road_cache) for raw_camera in raw_cameras]

    def get_camera(self, internal_id: str) -> Optional[SourceCamera]:

        raw_camera = self._fetch_raw_camera(int(internal_id))

        if raw_camera is None:
            return None

        return self._normalise(raw_camera, road_cache={})

    def get_latest_image(self, internal_id: str, image_url: Optional[str] = None) -> Optional[bytes]:

        # Always cheaply derivable from the ID alone - no lookup to skip.
        image_url = image_url or self._image_url(int(internal_id))

        try:
            response = self.session.get(image_url, timeout=self.request_timeout)
            response.raise_for_status()
            return response.content

        except requests.RequestException as error:
            self.logger.warning("Failed to fetch image for %s: %s", internal_id, error)
            return None

    # ------------------------------------------------------------------
    # Discovery: scan the ID range for cameras that actually exist
    # ------------------------------------------------------------------

    def _image_url(self, camera_id: int) -> str:
        return f"{self.base_url}/images/{camera_id:05d}.jpg"

    def _page_url(self, camera_id: int) -> str:
        return f"{self.base_url}/html/{camera_id:05d}.html"

    def _scan_camera_ids(self) -> list[dict]:

        raw_cameras = []

        with ThreadPoolExecutor(max_workers=self.workers) as executor:

            futures = [
                executor.submit(self._fetch_raw_camera, camera_id)
                for camera_id in range(self.start_id, self.end_id + 1)
            ]

            for future in as_completed(futures):

                result = future.result()

                if result:
                    raw_cameras.append(result)
                    print(f"[FOUND] {result['id']} | {result['description']}")

        return raw_cameras

    def _fetch_raw_camera(self, camera_id: int) -> Optional[dict]:

        image_url = self._image_url(camera_id)
        html_url = self._page_url(camera_id)

        try:
            # Check the JPG first with a cheap HEAD request before paying for
            # the full HTML page - most IDs in the range don't exist at all.
            with self.session.head(image_url, timeout=10, allow_redirects=True) as image:

                if image.status_code == 405:

                    with self.session.get(image_url, timeout=10, stream=True) as image:

                        if image.status_code != 200:
                            return None

                        content_type = image.headers.get("Content-Type", "").lower()

                else:

                    if image.status_code != 200:
                        return None

                    content_type = image.headers.get("Content-Type", "").lower()

            if not content_type.startswith("image/"):
                return None

            page = self.session.get(html_url, timeout=10)

            if page.status_code != 200:
                return None

            text = BeautifulSoup(page.text, "html.parser").get_text(" ", strip=True)

            description = None
            match = self.DESCRIPTION_RE.search(text)
            if match:
                description = match.group(2).strip()

            # Cameras marked "not available"/"unavailable" have no useful
            # feed - drop them rather than keeping a dead entry.
            if self.UNAVAILABLE_RE.search(description or text):
                return None

            carriageway = None
            match = self.CARRIAGEWAY_RE.search(text)
            if match:
                carriageway = match.group(1).strip()

            return {
                "id": f"{camera_id:05d}",
                "description": description,
                "carriageway": carriageway,
                "image_url": image_url,
                "page_url": html_url,
            }

        except requests.RequestException:
            return None

    # ------------------------------------------------------------------
    # Location: match each camera's description to a road geometry
    # ------------------------------------------------------------------

    def _parse_description(self, description: Optional[str]) -> dict:

        if not description:
            return {"road": None, "chainage": None, "junction": None}

        description = description.upper().strip()

        road_match = self.ROAD_RE.search(description)
        chainage_match = self.CHAINAGE_RE.search(description)
        junction_match = self.JUNCTION_RE.search(description)

        return {
            "road": road_match.group(1) if road_match else None,
            "chainage": chainage_match.group(1) if chainage_match else None,
            "junction": junction_match.group(1) if junction_match else None,
        }

    def _normalise_text(self, value: Any) -> str:

        if value is None:
            return ""

        return self.NON_ALNUM_RE.sub("", str(value).upper())

    def _normalise_direction(self, value: Optional[str]) -> Optional[str]:

        if not value:
            return None

        value = value.upper()

        if "ANTI" in value or "ACW" in value:
            return "ACW"
        if "CLOCKWISE" in value or value == "CW":
            return "CW"
        if "NORTH" in value:
            return "N"
        if "SOUTH" in value:
            return "S"
        if "EAST" in value:
            return "E"
        if "WEST" in value:
            return "W"

        return None

    def _query_road(self, road: str) -> list[dict]:

        if not road:
            return []

        safe_road = road.replace("'", "''")

        params = {
            "where": (
                f"UPPER(roadname) = '{safe_road}' "
                f"OR UPPER(linkdesc) LIKE '%{safe_road}%'"
            ),
            "outFields": "objectid,linkid,linkref,linkdesc,roadname,direction,carriageway,linkform",
            "returnGeometry": "true",
            "outSR": "3857",
            "f": "geojson",
        }

        try:
            response = requests.get(
                self.feature_server,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=self.request_timeout,
            )

            response.raise_for_status()

            return response.json().get("features", [])

        except requests.RequestException as error:
            self.logger.warning("FeatureServer query failed for road %s: %s", road, error)
            return []

    def _score_link(self, feature: dict, raw_camera: dict) -> int:

        properties = feature.get("properties", {})

        parsed = self._parse_description(raw_camera.get("description", ""))

        chainage = parsed["chainage"]
        junction = parsed["junction"]

        linkref = self._normalise_text(properties.get("linkref"))
        linkdesc = self._normalise_text(properties.get("linkdesc"))
        roadname = self._normalise_text(properties.get("roadname"))

        link_direction = self._normalise_direction(properties.get("direction"))
        camera_direction = self._normalise_direction(raw_camera.get("carriageway"))

        score = 0

        if parsed["road"]:
            if self._normalise_text(parsed["road"]) == roadname:
                score += 30
            elif self._normalise_text(parsed["road"]) in linkdesc:
                score += 20

        if camera_direction and link_direction and camera_direction == link_direction:
            score += 50

        if chainage:
            chainage_normalised = self._normalise_text(chainage)
            if chainage_normalised in linkref:
                score += 100
            elif chainage_normalised in linkdesc:
                score += 80

        if junction:
            junction_normalised = self._normalise_text(junction)
            if junction_normalised in linkref:
                score += 60
            elif junction_normalised in linkdesc:
                score += 40

        description_words = self.WORD_RE.findall((raw_camera.get("description") or "").upper())

        for word in description_words:

            if len(word) < 2:
                continue

            word = self._normalise_text(word)

            if word in linkref:
                score += 5
            elif word in linkdesc:
                score += 3

        return score

    def _geometry_to_latlon(self, feature: dict) -> Optional[dict]:

        geometry = feature.get("geometry")

        if not geometry:
            return None

        try:
            line = shape(geometry)

            # Use the midpoint along the actual National Highways geometry.
            midpoint = line.interpolate(0.5, normalized=True)

            longitude, latitude = transform(self._transformer.transform, midpoint).coords[0]

            return {"latitude": round(latitude, 7), "longitude": round(longitude, 7)}

        except Exception as error:
            self.logger.warning("Geometry error: %s", error)
            return None

    def _locate(self, raw_camera: dict, road_cache: dict) -> tuple[Optional[float], Optional[float], Optional[dict]]:

        parsed = self._parse_description(raw_camera.get("description"))

        road = parsed["road"]

        if not road:
            return None, None, None

        if road not in road_cache:
            road_cache[road] = self._query_road(road)
            time.sleep(self.request_delay)

        features = road_cache[road]

        if not features:
            return None, None, None

        scored = sorted(
            ((self._score_link(feature, raw_camera), feature) for feature in features),
            key=lambda item: item[0],
            reverse=True,
        )

        best_score, best_feature = scored[0]

        coordinates = self._geometry_to_latlon(best_feature)

        if not coordinates:
            return None, None, None

        properties = best_feature.get("properties", {})

        link_info = {
            "linkid": properties.get("linkid"),
            "linkref": properties.get("linkref"),
            "roadname": properties.get("roadname"),
            "direction": properties.get("direction"),
            "carriageway": properties.get("carriageway"),
            "match_score": best_score,
        }

        return coordinates["latitude"], coordinates["longitude"], link_info

    def _normalise(self, raw_camera: dict, road_cache: dict) -> SourceCamera:

        parsed = self._parse_description(raw_camera.get("description"))

        latitude, longitude, link_info = self._locate(raw_camera, road_cache)

        extra = {
            "page_url": raw_camera.get("page_url"),
            "carriageway": raw_camera.get("carriageway"),
            "chainage": parsed["chainage"],
            "junction": parsed["junction"],
        }

        if link_info:
            extra["national_highways_link"] = link_info

        return SourceCamera(
            internal_id=raw_camera["id"],
            name=raw_camera.get("description"),
            latitude=latitude,
            longitude=longitude,
            road=parsed["road"],
            direction=self._normalise_direction(raw_camera.get("carriageway")),
            image_url=raw_camera.get("image_url"),
            extra=extra,
        )
