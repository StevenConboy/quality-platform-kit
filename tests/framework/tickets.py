"""Sample tickets and a factory.

There are two kinds of sample here:
  - named tickets (ELECTRICAL_URGENT, WITH_PII, ...) for tests that need a specific shape
  - a pool of varied tickets that make_ticket() rotates through, so a run of tests does not
    submit the same title fifty times

Every ticket produced by make_ticket() gets a fresh asset id, so the app's per-asset
category cache cannot leak state between tests, even against a shared live server.
"""

from __future__ import annotations

import itertools
import uuid
from typing import Any

# --- named samples ----------------------------------------------------------------------

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

# --- the rotating pool ------------------------------------------------------------------

SAMPLE_TICKETS: list[dict[str, str]] = [
    ELECTRICAL_URGENT,
    PLUMBING_LEAK,
    HVAC_NO_HEAT,
    {
        "title": "Emergency exit sign dark",
        "description": "The illuminated exit sign above the east stairwell door is out.",
        "asset_id": "EXIT-E-2",
    },
    {
        "title": "Outlet sparking in break room",
        "description": "Plugging in the kettle caused a visible spark and the outlet is warm.",
        "asset_id": "BREAK-2F",
    },
    {
        "title": "Toilet running continuously",
        "description": "Second stall in the ground floor restroom refills every few minutes.",
        "asset_id": "RESTROOM-G-2",
    },
    {
        "title": "Conference room too warm",
        "description": "Room 4B has been at 78F all week. Thermostat set to 70F and unresponsive.",
        "asset_id": "CONF-4B",
    },
    {
        "title": "Crack in stairwell ceiling",
        "description": "A hairline crack about a metre long appeared above the landing overnight.",
        "asset_id": "STAIR-N-3",
    },
    {
        "title": "Smoke alarm chirping",
        "description": "Detector in the mail room chirps every thirty seconds. Probably a battery.",
        "asset_id": "SMOKE-MAIL-1",
    },
    {
        "title": "Wifi dropping in warehouse",
        "description": "Handheld scanners lose connection near bay 7 several times an hour.",
        "asset_id": "AP-WH-7",
    },
    {
        "title": "Loading dock door stuck half open",
        "description": "Roller door on bay 2 stopped at chest height and will not move either way.",
        "asset_id": "DOCK-DOOR-2",
    },
    {
        "title": "Gas smell near boiler room",
        "description": "Faint gas odour in the corridor outside the boiler room since about 9am.",
        "asset_id": "BOILER-B1",
    },
    {
        "title": "Printer jamming on every job",
        "description": "Third floor copier jams in the duplex unit on every print since Monday.",
        "asset_id": "PRN-3F-1",
    },
    {
        "title": "Flickering lights in car park",
        "description": "Half the fixtures on level P2 flicker constantly and two are fully out.",
        "asset_id": "LIGHT-P2",
    },
    {
        "title": "Ceiling tile water stain",
        "description": "Brown stain spreading on a ceiling tile by the window in room 210. No drip yet.",
        "asset_id": "OFFICE-210",
    },
    {
        "title": "Sprinkler head leaking",
        "description": "Small steady drip from a sprinkler head in aisle 4 of the archive room.",
        "asset_id": "SPRINK-ARCH-4",
    },
    {
        "title": "Squeaky door hinge",
        "description": "Door to the supply closet squeaks loudly. Minor, fix when convenient.",
        "asset_id": "CLOSET-1F",
    },
]

_rotation = itertools.cycle(SAMPLE_TICKETS)


def unique_asset_id(prefix: str = "ASSET") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def make_ticket(base: dict[str, str] | None = None, **overrides: Any) -> dict[str, Any]:
    """Copy a sample ticket with a fresh asset id, applying any overrides.

    With no base, the next ticket from the pool is used, so consecutive calls differ.
    """
    if base is None:
        base = next(_rotation)
    ticket: dict[str, Any] = {**base, "asset_id": unique_asset_id(base["asset_id"])}
    ticket.update(overrides)
    return ticket
