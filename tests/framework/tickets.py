"""Sample tickets and a factory. Asset ids are unique per call so the app's per-asset
category cache cannot leak state between tests, even against a shared live server."""

from __future__ import annotations

import uuid
from typing import Any

ELECTRICAL_URGENT: dict[str, str] = {
    "title": "Breaker tripping in server room",
    "description": "Main breaker for rack B trips every few hours. Smell of burning plastic.",
    "asset_id": "SRV-ROOM-2",
}

PLUMBING_LEAK: dict[str, str] = {
    "title": "Water pooling under sink",
    "description": "Slow drip from the supply line, cabinet floor is wet.",
    "asset_id": "KITCHEN-4",
}

HVAC_NO_HEAT: dict[str, str] = {
    "title": "No heat on floor 3",
    "description": "Thermostat reads 58F since this morning and the vents are blowing cold air.",
    "asset_id": "HVAC-3",
}

COSMETIC: dict[str, str] = {
    "title": "Scuffed paint in lobby",
    "description": "Minor scratch on the wall by the entrance. Cosmetic only, fix when convenient.",
    "asset_id": "LOBBY-1",
}

WITH_PII: dict[str, str] = {
    "title": "Badge reader offline",
    "description": (
        "Badge reader at the loading dock is dead. "
        "Contact Sam at 555-010-9999 or sam@example.com for access."
    ),
    "asset_id": "DOCK-READER-1",
}


def unique_asset_id(prefix: str = "ASSET") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def make_ticket(base: dict[str, str] = ELECTRICAL_URGENT, **overrides: Any) -> dict[str, Any]:
    """Copy a sample ticket with a fresh asset id, applying any overrides."""
    ticket: dict[str, Any] = {**base, "asset_id": unique_asset_id()}
    ticket.update(overrides)
    return ticket
