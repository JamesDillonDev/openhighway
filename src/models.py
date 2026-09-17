"""Typed data models shared across OpenHighways: what a source reports about
a camera, and what OpenHighways itself stores once that camera has a
master_id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SourceCamera:
    """A camera as reported by a single provider, before it enters OpenHighways.

    `internal_id` is opaque and provider-specific - only meaningful combined
    with the source's own name. Sources must never set a master_id.
    """

    internal_id: str
    name: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    road: Optional[str] = None
    direction: Optional[str] = None
    image_url: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class CameraRecord:
    """A camera as stored in the OpenHighways database - has both IDs."""

    master_id: int
    source: str
    internal_id: str
    name: Optional[str]
    road: Optional[str]
    direction: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    image_url: Optional[str]
    active: bool
    vehicles: Optional[int]
    last_seen: str
    created_at: str
    updated_at: str
