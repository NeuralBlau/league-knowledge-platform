"""Generate and validate a versioned League of Legends champion target catalog."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "champion_targets.json"
VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
PROVIDER = "Riot Games Data Dragon"
LOCALE = "en_US"
SCHEMA_VERSION = 1
VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")


class CatalogError(ValueError):
    """The Riot roster or local catalog is invalid."""


def roster_url(version: str) -> str:
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        raise CatalogError("Data Dragon roster version must have the form major.minor.patch")
    return f"https://ddragon.leagueoflegends.com/cdn/{version}/data/{LOCALE}/champion.json"


def fetch_json(url: str) -> object:
    request = Request(url, headers={"User-Agent": "league-knowledge-platform-champion-catalog/1"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def current_version(fetcher=fetch_json) -> str:
    versions = fetcher(VERSIONS_URL)
    if not isinstance(versions, list) or not versions:
        raise CatalogError("Data Dragon version list is empty or malformed")
    version = versions[0]
    roster_url(version)
    return version


def normalize_champions(payload: object, version: str) -> list[dict[str, str]]:
    if not isinstance(payload, dict) or payload.get("version") != version:
        raise CatalogError("Champion roster payload does not match the selected version")
    records = payload.get("data")
    if not isinstance(records, dict) or not records:
        raise CatalogError("Champion roster has no valid data mapping")

    champions: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    for map_id, record in records.items():
        if not isinstance(record, dict):
            raise CatalogError("Champion roster contains a malformed record")
        champion_id = record.get("id")
        key = record.get("key")
        name = record.get("name")
        if (
            not isinstance(map_id, str)
            or not isinstance(champion_id, str)
            or not champion_id
            or champion_id != map_id
            or champion_id != champion_id.strip()
        ):
            raise CatalogError("Champion roster contains a missing or inconsistent ID")
        if not isinstance(key, str) or not key.isascii() or not key.isdecimal():
            raise CatalogError(f"Champion {champion_id} has an invalid Riot key")
        if key in seen_keys:
            raise CatalogError(f"Champion roster repeats Riot key {key}")
        if not isinstance(name, str) or not name.strip():
            raise CatalogError(f"Champion {champion_id} has no name")
        seen_keys.add(key)
        champions.append({"id": champion_id, "key": key, "name": name})

    return sorted(champions, key=lambda champion: champion["id"])


def build_catalog(version: str, payload: object, generated_at: str) -> dict:
    url = roster_url(version)
    if not isinstance(generated_at, str) or not generated_at:
        raise CatalogError("Generation timestamp is missing")
    return {
        "schema_version": SCHEMA_VERSION,
        "roster_version": version,
        "generated_at": generated_at,
        "source": {"provider": PROVIDER, "url": url, "locale": LOCALE},
        "champions": normalize_champions(payload, version),
    }


def write_catalog(path: Path, catalog: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(catalog, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def generate(path: Path, fetcher=fetch_json, generated_at: str | None = None) -> dict:
    version = current_version(fetcher)
    payload = fetcher(roster_url(version))
    timestamp = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    catalog = build_catalog(version, payload, timestamp)
    write_catalog(path, catalog)
    return catalog


def check(path: Path, fetcher=fetch_json) -> dict:
    with path.open(encoding="utf-8") as source:
        catalog = json.load(source)
    if not isinstance(catalog, dict):
        raise CatalogError("Champion catalog must be a JSON object")
    version = catalog.get("roster_version")
    url = roster_url(version)
    generated_at = catalog.get("generated_at")
    if not isinstance(generated_at, str):
        raise CatalogError("Champion catalog has no generation timestamp")
    try:
        timestamp = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise CatalogError("Champion catalog has an invalid generation timestamp") from error
    if timestamp.utcoffset() != timezone.utc.utcoffset(None):
        raise CatalogError("Champion catalog generation timestamp must be UTC")
    expected = build_catalog(version, fetcher(url), generated_at)
    if catalog != expected:
        raise CatalogError("Champion catalog differs from the recorded Data Dragon roster or schema")
    return catalog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("generate", "check"):
        command = commands.add_parser(name)
        command.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        catalog = generate(args.output) if args.command == "generate" else check(args.output)
    except (CatalogError, OSError, URLError, json.JSONDecodeError) as error:
        parser.exit(1, f"{args.command} failed: {error}\n")
    print(f"{args.command}: {len(catalog['champions'])} champions at Data Dragon {catalog['roster_version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
