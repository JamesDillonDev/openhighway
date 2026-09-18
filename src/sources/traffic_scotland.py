"""Traffic Scotland source: downloads CCTV camera images from Traffic
Scotland's "Live Traffic Camera FTP Service".

Unlike National Highways and TfL, this feed is NOT publicly open - Traffic
Scotland only makes it available to approved subscribers (see
https://www.traffic.gov.scot/traffic-scotland-developer-hub, or email
info@trafficscotland.org to request access). Until real credentials and the
exact directory/file-naming layout from their onboarding docs are supplied,
this source cleanly reports itself as unconfigured rather than guessing at
undocumented behaviour - the master pipeline already treats a single
source's failure as non-fatal, so this doesn't block National Highways/TfL.
"""

from __future__ import annotations

import io
import os
import re
from ftplib import FTP
from typing import Optional

from config import section
from models import SourceCamera

from .source import Source


class TrafficScotlandSource(Source):

    name = "traffic_scotland"

    ROAD_RE = re.compile(r"\b((?:M|A)\d+(?:\(M\))?)\b", re.IGNORECASE)

    def __init__(self) -> None:

        super().__init__()

        settings = section("sources")["traffic_scotland"]

        self.ftp_host = settings.get("ftp_host") or None
        self.ftp_directory = settings.get("ftp_directory", "/")
        self.request_timeout = settings.get("request_timeout", 30)

        # Credentials are secrets - never read from config.json, only env.
        self.ftp_username = os.environ.get("TRAFFIC_SCOTLAND_FTP_USER")
        self.ftp_password = os.environ.get("TRAFFIC_SCOTLAND_FTP_PASSWORD")

        self.configured = bool(self.ftp_host and self.ftp_username and self.ftp_password)

    def metadata(self) -> dict:
        return {
            "name": self.name,
            "display_name": "Traffic Scotland",
            "coverage": "Scotland trunk road network",
            "configured": self.configured,
        }

    # ------------------------------------------------------------------
    # Source interface
    # ------------------------------------------------------------------

    def discover_cameras(self) -> list[SourceCamera]:

        self._require_configured()

        with self._connect() as ftp:
            filenames = self._list_image_files(ftp)

        return [self._normalise(filename) for filename in filenames]

    def get_camera(self, internal_id: str) -> Optional[SourceCamera]:

        self._require_configured()

        with self._connect() as ftp:
            filenames = self._list_image_files(ftp)

        for filename in filenames:
            if self._camera_id(filename) == internal_id:
                return self._normalise(filename)

        return None

    def get_latest_image(self, internal_id: str, image_url: Optional[str] = None) -> Optional[bytes]:

        self._require_configured()

        try:
            with self._connect() as ftp:
                buffer = io.BytesIO()
                ftp.retrbinary(f"RETR {internal_id}.jpg", buffer.write)
                return buffer.getvalue()

        except Exception as error:
            self.logger.warning("Failed to fetch image for %s: %s", internal_id, error)
            return None

    # ------------------------------------------------------------------
    # FTP access - fill in directory/naming specifics once Traffic
    # Scotland's onboarding docs confirm the real layout.
    # ------------------------------------------------------------------

    def _require_configured(self) -> None:

        if not self.configured:
            raise RuntimeError(
                "Traffic Scotland source is not configured - it requires approved-subscriber "
                "FTP access (request it via info@trafficscotland.org or the Data Hub at "
                "https://www.traffic.gov.scot/traffic-scotland-developer-hub), then set "
                "sources.traffic_scotland.ftp_host in config.json plus the "
                "TRAFFIC_SCOTLAND_FTP_USER / TRAFFIC_SCOTLAND_FTP_PASSWORD environment variables."
            )

    def _connect(self) -> FTP:

        ftp = FTP(self.ftp_host, timeout=self.request_timeout)
        ftp.login(self.ftp_username, self.ftp_password)
        ftp.cwd(self.ftp_directory)

        return ftp

    def _list_image_files(self, ftp: FTP) -> list[str]:
        return [name for name in ftp.nlst() if name.lower().endswith(".jpg")]

    def _camera_id(self, filename: str) -> str:
        return filename.rsplit(".", 1)[0]

    def _normalise(self, filename: str) -> SourceCamera:

        camera_id = self._camera_id(filename)
        # Best-effort until the real manifest format is known - filenames
        # are the only camera metadata available without it.
        name = camera_id.replace("_", " ").strip()

        road_match = self.ROAD_RE.search(name.upper())

        return SourceCamera(
            internal_id=camera_id,
            name=name or None,
            latitude=None,
            longitude=None,
            road=road_match.group(1) if road_match else None,
            direction=None,
            image_url=None,
            extra={"filename": filename},
        )
