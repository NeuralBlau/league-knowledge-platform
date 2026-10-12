"""Read the committed Champion target catalog without contacting Riot."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .models import ChampionTarget

DEFAULT_CATALOG = Path(__file__).resolve().parents[1] / "data" / "champion_targets.json"
_ROSTER_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
_EXPECTED_TOP_LEVEL = {"schema_version", "roster_version", "generated_at", "source", "champions"}
_EXPECTED_SOURCE = {"provider", "url", "locale"}
_EXPECTED_CHAMPION = {"id", "key", "name"}


class TargetLoadError(ValueError):
    """The Champion target catalog cannot be loaded completely."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TargetLoadError(message)


def load_targets(path: Path = DEFAULT_CATALOG) -> tuple[ChampionTarget, ...]:
    """Validate and return every configured Champion target, or fail atomically."""
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TargetLoadError("Champion target catalog could not be read as JSON") from error

    _require(isinstance(catalog, dict) and set(catalog) == _EXPECTED_TOP_LEVEL,
             "Champion target catalog has an invalid top-level structure")
    _require(type(catalog["schema_version"]) is int and catalog["schema_version"] == 1,
             "Unsupported Champion target catalog schema")
    version = catalog["roster_version"]
    _require(isinstance(version, str) and bool(_ROSTER_VERSION.fullmatch(version)),
             "Champion target catalog has an invalid roster version")

    generated_at = catalog["generated_at"]
    _require(isinstance(generated_at, str), "Champion target catalog has no generation time")
    try:
        timestamp = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise TargetLoadError("Champion target catalog has an invalid generation time") from error
    _require(timestamp.utcoffset() == timezone.utc.utcoffset(None),
             "Champion target catalog generation time must be UTC")

    source = catalog["source"]
    _require(isinstance(source, dict) and set(source) == _EXPECTED_SOURCE,
             "Champion target catalog has invalid source provenance")
    expected_url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json"
    _require(source["provider"] == "Riot Games Data Dragon"
             and source["locale"] == "en_US" and source["url"] == expected_url,
             "Champion target catalog source does not match its roster version")

    entries = catalog["champions"]
    _require(isinstance(entries, list) and bool(entries),
             "Champion target catalog contains no Champion entries")
    targets: list[ChampionTarget] = []
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()
    for entry in entries:
        _require(isinstance(entry, dict) and set(entry) == _EXPECTED_CHAMPION,
                 "Champion target catalog contains an invalid entry")
        champion_id, key, name = entry["id"], entry["key"], entry["name"]
        _require(isinstance(champion_id, str) and bool(champion_id)
                 and champion_id == champion_id.strip(),
                 "Champion target catalog contains an invalid Champion ID")
        _require(isinstance(key, str) and key.isascii() and key.isdecimal(),
                 "Champion target catalog contains an invalid Riot key")
        _require(isinstance(name, str) and bool(name.strip()),
                 "Champion target catalog contains a Champion without a name")
        _require(champion_id not in seen_ids and key not in seen_keys,
                 "Champion target catalog contains a duplicate identity")
        seen_ids.add(champion_id)
        seen_keys.add(key)
        targets.append(ChampionTarget(id=champion_id, key=key, name=name))
    return tuple(targets)
