"""TfL source: discovers London traffic cameras (JamCams) from the
Transport for London Unified API.

Entirely independent of National Highways - TfL has its own ID format, its
own location data, and doesn't require any road-geometry lookup since it
already provides coordinates directly.
"""

from __future__ import annotations

import os
import re
from typing import Any, Optional

import requests

from config import USER_AGENT, section
from models import SourceCamera

from .source import Source


class TfLSource(Source):

    name = "tfl"

    PLACES_ENDPOINT = "/Place/Type/JamCam"
    PLACE_ENDPOINT = "/Place/{id}"

    ROAD_RE = re.compile(r"\b((?:M|A)\d+(?:\(M\))?)\b", re.IGNORECASE)

    def __init__(self) -> None:

        super().__init__()

        settings = section("sources")["tfl"]

        self.base_url = settings["base_url"]
        self.request_timeout = settings.get("request_timeout", 15)

        # Optional - the TfL API works unauthenticated at low volume, but an
        # app key raises the rate limit. Never hard-code it: read from env.
        self.app_key = os.environ.get("TFL_APP_KEY")

        self.session = self._build_session(USER_AGENT, workers=1)

    def metadata(self) -> dict:
        return {
            "name": self.name,
            "display_name": "Transport for London",
            "coverage": "Greater London (JamCams)",
        }

    # ------------------------------------------------------------------
    # Source interface
    # ------------------------------------------------------------------

    def discover_cameras(self) -> list[SourceCamera]:

        places = self._request(self.PLACES_ENDPOINT)
        cameras = [self._normalise(place) for place in places]

        for camera in cameras:
            print(f"[FOUND] {camera.internal_id} | {camera.name}")

        return cameras

    def get_camera(self, internal_id: str) -> Optional[SourceCamera]:

        try:
            place = self._request(self.PLACE_ENDPOINT.format(id=internal_id))
        except requests.RequestException:
            return None

        # /Place/{id} returns a list with zero or one place
        if isinstance(place, list):
            place = place[0] if place else None

        return self._normalise(place) if place else None

    def get_latest_image(self, internal_id: str, image_url: Optional[str] = None) -> Optional[bytes]:

        # Skip the metadata lookup entirely if the caller already has a
        # cached URL - JamCam image URLs are stable, so there's no need to
        # re-fetch camera metadata on every single image poll.
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
    # TfL API access
    # ------------------------------------------------------------------

    def _request(self, path: str) -> Any:

        params = {"app_key": self.app_key} if self.app_key else {}

        response = self.session.get(f"{self.base_url}{path}", params=params, timeout=self.request_timeout)
        response.raise_for_status()

        return response.json()

    def _extract_property(self, place: dict, key: str) -> Optional[str]:

        for prop in place.get("additionalProperties", []):
            if prop.get("key") == key:
                return prop.get("value")

        return None

    def _parse_road(self, common_name: Optional[str]) -> Optional[str]:

        if not common_name:
            return None

        match = self.ROAD_RE.search(common_name)

        return match.group(1).upper() if match else None

    def _normalise(self, place: dict) -> SourceCamera:

        return SourceCamera(
            internal_id=place["id"],
            name=place.get("commonName"),
            latitude=place.get("lat"),
            longitude=place.get("lon"),
            road=self._parse_road(place.get("commonName")),
            direction=None,
            image_url=self._extract_property(place, "imageUrl"),
            extra={"place_type": place.get("placeType")},
        )
