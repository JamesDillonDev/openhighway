"""Master pipeline: coordinates every configured Source and syncs their
cameras into the database.

Provider-agnostic by design - it only ever calls the `Source` interface, so
adding a new provider never requires a change here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import db
from sources.source import Source

logger = logging.getLogger("openhighway.pipeline")


@dataclass
class SourceRunResult:
    source: str
    status: str  # "ok" or "error"
    camera_count: int = 0
    deactivated_count: int = 0
    error: Optional[str] = None


class MasterPipeline:

    def __init__(self, sources: list[Source], db_path=None):
        self.sources = sources
        self.db_path = db_path

    def run(self) -> list[SourceRunResult]:

        conn = db.get_connection(self.db_path)
        db.init_db(conn)

        try:
            return [self._run_source(conn, source) for source in self.sources]
        finally:
            conn.close()

    def _run_source(self, conn, source: Source) -> SourceRunResult:

        try:
            cameras = source.discover_cameras()

        except Exception as error:
            # A failure in one source must never stop the others.
            logger.error("Source '%s' failed: %s", source.name, error, exc_info=True)
            return SourceRunResult(source=source.name, status="error", error=str(error))

        seen_at = datetime.now(timezone.utc).isoformat()

        for camera in cameras:
            db.upsert_camera(conn, source.name, camera, seen_at=seen_at)

        deactivated = db.deactivate_missing(
            conn, source.name, (camera.internal_id for camera in cameras), seen_at=seen_at
        )

        logger.info(
            "Source '%s': %d cameras synced, %d marked inactive",
            source.name, len(cameras), deactivated,
        )

        return SourceRunResult(
            source=source.name,
            status="ok",
            camera_count=len(cameras),
            deactivated_count=deactivated,
        )
