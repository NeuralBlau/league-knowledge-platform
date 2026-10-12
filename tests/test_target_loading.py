"""Offline tests for atomic loading of the committed Champion catalog."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from league_knowledge_platform import TargetLoadError, load_targets
from league_knowledge_platform.targets import DEFAULT_CATALOG


class TargetLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(DEFAULT_CATALOG.read_text(encoding="utf-8"))

    def test_committed_catalog_loads_completely(self):
        targets = load_targets()
        self.assertEqual(len(targets), len(self.catalog["champions"]))
        self.assertEqual([target.id for target in targets],
                         [entry["id"] for entry in self.catalog["champions"]])
        self.assertEqual(len({target.id for target in targets}), len(targets))
        self.assertEqual(len({target.key for target in targets}), len(targets))
        self.assertEqual((targets[0].id, targets[0].key, targets[0].name),
                         ("Aatrox", "266", "Aatrox"))

    def test_missing_or_unreadable_catalog_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in (root / "missing.json", root):
                with self.subTest(path=path):
                    with self.assertRaises(TargetLoadError):
                        load_targets(path)

    def test_invalid_catalog_fails_without_returning_a_partial_set(self):
        cases = {
            "unsupported schema": lambda x: x.update(schema_version=2),
            "missing provenance": lambda x: x.pop("source"),
            "wrong source version": lambda x: x["source"].update(url="https://example.com"),
            "empty targets": lambda x: x.update(champions=[]),
            "missing late entry name": lambda x: x["champions"][-1].pop("name"),
            "duplicate champion ID": lambda x: x["champions"][-1].update(id=x["champions"][0]["id"]),
            "duplicate Riot key": lambda x: x["champions"][-1].update(key=x["champions"][0]["key"]),
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            for label, change in cases.items():
                with self.subTest(label=label):
                    catalog = copy.deepcopy(self.catalog)
                    change(catalog)
                    path.write_text(json.dumps(catalog), encoding="utf-8")
                    with self.assertRaises(TargetLoadError):
                        load_targets(path)

    def test_malformed_json_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(TargetLoadError):
                load_targets(path)


if __name__ == "__main__":
    unittest.main()
