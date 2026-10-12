"""Offline contract tests for the versioned champion target catalog."""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import champion_targets as targets  # noqa: E402

VERSION = "16.20.1"
TIMESTAMP = "2026-10-12T10:00:00Z"


def roster():
    return {
        "version": VERSION,
        "data": {
            "RenataGlasc": {"id": "RenataGlasc", "key": "888", "name": "Renata Glasc"},
            "Aatrox": {"id": "Aatrox", "key": "266", "name": "Aatrox"},
            "Ahri": {"id": "Ahri", "key": "103", "name": "Ahri"},
        },
    }


class ChampionTargetsTests(unittest.TestCase):
    def test_normalization_is_deterministic_and_has_no_roles(self):
        first = targets.build_catalog(VERSION, roster(), TIMESTAMP)
        reversed_roster = roster()
        reversed_roster["data"] = dict(reversed(list(reversed_roster["data"].items())))
        second = targets.build_catalog(VERSION, reversed_roster, TIMESTAMP)

        self.assertEqual(first, second)
        self.assertEqual(first["champions"], targets.build_catalog(VERSION, roster(), "2026-10-13T10:00:00Z")["champions"])
        self.assertEqual([entry["id"] for entry in first["champions"]], ["Aatrox", "Ahri", "RenataGlasc"])
        self.assertEqual(first["champions"][0], {"id": "Aatrox", "key": "266", "name": "Aatrox"})
        self.assertEqual(first["schema_version"], 1)
        self.assertEqual(first["roster_version"], VERSION)
        self.assertEqual(first["generated_at"], TIMESTAMP)
        self.assertEqual(
            first["source"],
            {
                "provider": "Riot Games Data Dragon",
                "url": targets.roster_url(VERSION),
                "locale": "en_US",
            },
        )
        self.assertTrue(all(set(entry) == {"id", "key", "name"} for entry in first["champions"]))

    def test_generate_then_check_uses_recorded_version_and_never_latest(self):
        requested = []

        def fetch_for_generate(url):
            requested.append(url)
            if url == targets.VERSIONS_URL:
                return [VERSION, "16.19.1"]
            if url == targets.roster_url(VERSION):
                return roster()
            self.fail(f"Unexpected URL: {url}")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            generated = targets.generate(path, fetch_for_generate, TIMESTAMP)
            self.assertEqual(requested, [targets.VERSIONS_URL, targets.roster_url(VERSION)])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), generated)

            checked_urls = []

            def fetch_for_check(url):
                checked_urls.append(url)
                self.assertEqual(url, targets.roster_url(VERSION))
                return roster()

            before_check = path.read_bytes()
            self.assertEqual(targets.check(path, fetch_for_check), generated)
            self.assertEqual(path.read_bytes(), before_check)
            self.assertEqual(checked_urls, [targets.roster_url(VERSION)])

    def test_check_rejects_missing_extra_changed_and_reordered_champions(self):
        canonical = targets.build_catalog(VERSION, roster(), TIMESTAMP)
        cases = {
            "missing": lambda entries: entries.pop(),
            "extra": lambda entries: entries.append({"id": "Invented", "key": "999", "name": "Invented"}),
            "changed": lambda entries: entries[0].update(name="Wrong"),
            "reordered": lambda entries: entries.reverse(),
            "duplicate": lambda entries: entries.append(entries[0].copy()),
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            for label, change in cases.items():
                with self.subTest(label=label):
                    altered = copy.deepcopy(canonical)
                    change(altered["champions"])
                    path.write_text(json.dumps(altered), encoding="utf-8")
                    with self.assertRaisesRegex(targets.CatalogError, "differs"):
                        targets.check(path, lambda url: roster())

    def test_invalid_source_records_are_rejected(self):
        mismatched_version = roster()
        mismatched_version["version"] = "16.19.1"
        with self.assertRaisesRegex(targets.CatalogError, "selected version"):
            targets.normalize_champions(mismatched_version, VERSION)

        duplicate_key = roster()
        duplicate_key["data"]["Ahri"]["key"] = "266"
        with self.assertRaisesRegex(targets.CatalogError, "repeats Riot key"):
            targets.normalize_champions(duplicate_key, VERSION)

        mismatched_id = roster()
        mismatched_id["data"]["Ahri"]["id"] = "Wrong"
        with self.assertRaisesRegex(targets.CatalogError, "inconsistent ID"):
            targets.normalize_champions(mismatched_id, VERSION)

    def test_failed_generation_preserves_previous_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text("previous artifact\n", encoding="utf-8")

            def invalid_source(url):
                return [VERSION] if url == targets.VERSIONS_URL else {"version": VERSION, "data": {}}

            with self.assertRaisesRegex(targets.CatalogError, "no valid data"):
                targets.generate(path, invalid_source, TIMESTAMP)
            self.assertEqual(path.read_text(encoding="utf-8"), "previous artifact\n")

    def test_invalid_local_provenance_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            catalog = targets.build_catalog(VERSION, roster(), TIMESTAMP)
            catalog["roster_version"] = "../latest"
            path.write_text(json.dumps(catalog), encoding="utf-8")

            def no_network(url):
                self.fail(f"Unexpected fetch: {url}")

            with self.assertRaisesRegex(targets.CatalogError, "roster version"):
                targets.check(path, no_network)


if __name__ == "__main__":
    unittest.main()
