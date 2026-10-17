"""Real local Bronze/SQLite ordering, failure injection and restart recovery."""

from contextlib import closing, contextmanager
from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from league_knowledge_platform import (
    BronzeConfig, BronzeContractError, BronzeFilesystemError, BronzeIntegrationContext,
    BronzeIntegrityError, BronzeRegistrationError, ChampionTarget, canonical_bronze_path,
    decode_bronze_artifact, initialize_source_catalog, integrate_selected_source,
)
from league_knowledge_platform import _bronze_filesystem as filesystem
from test_bronze import NOW, selected_source


@contextmanager
def database(path):
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            yield connection


class BronzeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = BronzeConfig(self.root / "bronze")
        self.catalog = initialize_source_catalog(self.root / "catalog.sqlite3")
        self.spy = Mock(wraps=self.catalog)
        self.selected = selected_source()
        self.path = canonical_bronze_path("A", self.config)

    def integrate(self, selected=None, **kwargs):
        return integrate_selected_source(selected or self.selected, catalog=self.spy, config=self.config, **kwargs)

    def test_first_integration_validates_durable_file_before_registration(self):
        def register(video_id):
            self.assertEqual(decode_bronze_artifact(self.path.read_bytes())["source"]["video_id"], video_id)
            self.assertEqual(list(self.path.parent.iterdir()), [self.path])
            return self.catalog.register_integrated(video_id)
        self.spy.register_integrated.side_effect = register
        with patch.object(filesystem, "confirm_durable", wraps=filesystem.confirm_durable) as durable:
            result = self.integrate(context=BronzeIntegrationContext(42, NOW))
        self.assertTrue(result.created)
        self.assertTrue(result.registered)
        self.assertTrue(self.catalog.is_integrated("A"))
        durable.assert_called_once_with(self.path)
        self.assertEqual({p.name for p in self.root.iterdir()}, {"bronze", "catalog.sqlite3"})
        with database(self.catalog.path) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables, {"schema_metadata", "integrated_sources"})

    def test_identical_retry_is_byte_preserving_and_keeps_registration_timestamp(self):
        self.integrate()
        before = self.path.read_bytes()
        timestamp = self.path.stat().st_mtime_ns
        with database(self.catalog.path) as connection:
            registered_at = connection.execute("SELECT registered_at_utc FROM integrated_sources").fetchone()
        with patch.object(filesystem, "stage", side_effect=AssertionError("Unexpected rewrite")):
            result = self.integrate()
        self.assertFalse(result.created)
        self.assertFalse(result.registered)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_mtime_ns, timestamp)
        with database(self.catalog.path) as connection:
            self.assertEqual(connection.execute("SELECT registered_at_utc FROM integrated_sources").fetchone(), registered_at)

    def test_registration_failure_retains_bronze_and_retry_completes_catalog(self):
        with database(self.catalog.path) as connection:
            connection.execute("CREATE TRIGGER fail_registration BEFORE INSERT ON integrated_sources BEGIN SELECT RAISE(ABORT, 'fixture'); END")
        with self.assertRaises(BronzeRegistrationError):
            self.integrate(context=BronzeIntegrationContext(42, NOW))
        before = self.path.read_bytes()
        self.assertFalse(self.catalog.is_integrated("A"))
        with database(self.catalog.path) as connection:
            connection.execute("DROP TRIGGER fail_registration")
        result = self.integrate(context=BronzeIntegrationContext("later-run", None))
        self.assertFalse(result.created)
        self.assertTrue(result.registered)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(decode_bronze_artifact(before)["acquisition"]["run_id"], 42)

    def test_later_target_run_and_selection_contexts_never_backfill_or_rewrite(self):
        self.integrate()
        before = self.path.read_bytes()
        for name in ("run", "target", "selection", "all"):
            with self.subTest(name=name):
                later = self.selected
                context = BronzeIntegrationContext("later" if name in ("run", "all") else None)
                if name in ("target", "all"):
                    candidate = replace(later.source.ranked_candidate.candidate, target_id="Vayne")
                    source = replace(later.source, ranked_candidate=replace(later.source.ranked_candidate, candidate=candidate))
                    later = replace(later, target_id="Vayne", source=source)
                    context = replace(context, target=ChampionTarget("Vayne", "67", "Vayne"))
                if name in ("selection", "all"):
                    comparative = selected_source("A", "B", winner="A")
                    later = replace(comparative, source=later.source, target_id=later.target_id)
                self.integrate(later, context=context)
                self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob("*.json")), [self.path])

    def test_case_distinct_sources_have_distinct_files_and_catalog_identities(self):
        self.integrate()
        result = self.integrate(selected_source("a"))
        self.assertNotEqual(result.path, self.path)
        self.assertEqual(self.catalog.load_integrated_ids(), frozenset({"A", "a"}))
        self.assertEqual(len(list(self.path.parent.glob("*.json"))), 2)

    def test_conflicting_transcript_never_overwrites_or_registers(self):
        self.integrate()
        before = self.path.read_bytes()
        segment = replace(self.selected.source.segments[0], source_text="Different source", text="Different source")
        later = replace(self.selected, source=replace(self.selected.source, segments=(segment,)))
        self.spy.reset_mock()
        with self.assertRaises(BronzeIntegrityError):
            self.integrate(later)
        self.assertEqual(self.path.read_bytes(), before)
        self.spy.register_integrated.assert_not_called()

    def test_corrupt_unsupported_and_wrong_identity_artifacts_are_not_replaced(self):
        self.integrate()
        artifact = decode_bronze_artifact(self.path.read_bytes())
        wrong_id = json.loads(json.dumps(artifact))
        wrong_id["source"].update(video_id="B", url="https://www.youtube.com/watch?v=B")
        wrong_id["selection"]["winner_quality"]["video_id"] = "B"
        for content in (b'{"partial":', json.dumps({**artifact, "schema_version": 2}).encode(), json.dumps(wrong_id).encode()):
            self.path.write_bytes(content)
            self.spy.reset_mock()
            with self.subTest(content=content[:20]), self.assertRaises(BronzeIntegrityError):
                self.integrate()
            self.assertEqual(self.path.read_bytes(), content)
            self.spy.register_integrated.assert_not_called()

    def test_catalog_entry_without_bronze_is_integrity_error_not_reconstruction(self):
        self.catalog.register_integrated("A")
        with self.assertRaises(BronzeIntegrityError):
            self.integrate()
        self.assertFalse(self.path.exists())
        self.spy.register_integrated.assert_not_called()

    def test_construction_failure_never_calls_catalog(self):
        with self.assertRaises(BronzeContractError):
            integrate_selected_source(object(), catalog=self.spy, config=self.config)
        self.assertEqual(self.spy.mock_calls, [])
        self.assertFalse(self.path.parent.exists())

    def test_atomic_visibility_before_and_after_publication(self):
        original = filesystem.publish
        def publish(temporary, final):
            self.assertFalse(final.exists())
            self.assertEqual(decode_bronze_artifact(temporary.read_bytes())["source"]["video_id"], "A")
            original(temporary, final)
            self.assertEqual(decode_bronze_artifact(final.read_bytes())["source"]["video_id"], "A")
            self.spy.register_integrated.assert_not_called()
        with patch.object(filesystem, "publish", side_effect=publish):
            self.integrate()

    def test_faults_before_registration_do_not_register_and_allow_retry(self):
        cases = (
            ("league_knowledge_platform.bronze.json.dumps", ValueError("serialization")),
            ("league_knowledge_platform._bronze_filesystem.prepare_directory", OSError("directory")),
            ("league_knowledge_platform._bronze_filesystem.stage", OSError("write")),
            ("league_knowledge_platform._bronze_filesystem.publish", OSError("rename")),
            ("league_knowledge_platform.bronze._read_canonical", OSError("final read")),
            ("league_knowledge_platform._bronze_filesystem.confirm_durable", OSError("flush")),
        )
        for target, error in cases:
            with self.subTest(target=target), TemporaryDirectory() as root:
                config = BronzeConfig(Path(root) / "bronze")
                catalog = Mock(wraps=initialize_source_catalog(Path(root) / "catalog.sqlite3"))
                with patch(target, side_effect=error), self.assertRaises(BronzeFilesystemError):
                    integrate_selected_source(self.selected, catalog=catalog, config=config)
                catalog.register_integrated.assert_not_called()
                self.assertEqual(list(config.root.rglob("*.tmp")), [])
                result = integrate_selected_source(self.selected, catalog=catalog, config=config)
                self.assertTrue(result.registered)

    def test_flush_failure_removes_own_temporary_file(self):
        original = filesystem.stage
        def fail_flush(*args):
            with patch.object(filesystem.os, "fsync", side_effect=OSError("flush")):
                return original(*args)
        with patch.object(filesystem, "stage", side_effect=fail_flush), self.assertRaises(BronzeFilesystemError):
            self.integrate()
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.path.parent.iterdir()), [])
        self.spy.register_integrated.assert_not_called()

    def test_temporary_validation_failure_never_publishes(self):
        original = filesystem.stage
        def corrupt(*args):
            temporary = original(*args)
            temporary.write_bytes(b'{"partial":')
            return temporary
        with patch.object(filesystem, "stage", side_effect=corrupt), \
                patch.object(filesystem, "publish") as publish, self.assertRaises(BronzeContractError):
            self.integrate()
        publish.assert_not_called()
        self.spy.register_integrated.assert_not_called()
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_publication_refuses_to_overwrite_existing_final_file(self):
        filesystem.prepare_directory(self.path.parent)
        temporary = filesystem.stage(self.path.parent, "41", b"incoming")
        self.path.write_bytes(b"original")
        with self.assertRaises(FileExistsError):
            filesystem.publish(temporary, self.path)
        self.assertEqual(self.path.read_bytes(), b"original")
        temporary.unlink()

    def test_restart_cleanup_is_source_specific_and_does_not_promote_temp_content(self):
        filesystem.prepare_directory(self.path.parent)
        own = self.path.parent / (".bronze-tmp-41-" + "a" * 32 + ".tmp")
        other = self.path.parent / (".bronze-tmp-42-" + "a" * 32 + ".tmp")
        unrelated = self.path.parent / "user.tmp"
        for path in (own, other, unrelated):
            path.write_bytes(b"partial")
        self.integrate()
        self.assertFalse(own.exists())
        self.assertTrue(other.exists())
        self.assertTrue(unrelated.exists())
        self.assertEqual(decode_bronze_artifact(self.path.read_bytes())["source"]["video_id"], "A")

    def test_existing_final_retry_cleans_interrupted_publication_temporary_alias(self):
        self.integrate()
        before = self.path.read_bytes()
        temporary = self.path.parent / (".bronze-tmp-41-" + "a" * 32 + ".tmp")
        os.link(self.path, temporary)
        self.integrate()
        self.assertFalse(temporary.exists())
        self.assertEqual(self.path.read_bytes(), before)

    def test_posix_publication_orders_link_directory_sync_and_temporary_removal(self):
        filesystem.prepare_directory(self.path.parent)
        temporary = filesystem.stage(self.path.parent, "41", b"complete")
        observed = []
        def sync(directory):
            observed.append((directory, self.path.read_bytes(), temporary.exists()))
        with patch.object(filesystem, "_PLATFORM", "posix"), \
                patch.object(filesystem, "sync_directory", side_effect=sync):
            filesystem.publish(temporary, self.path)
        self.assertEqual(observed, [(self.path.parent, b"complete", True),
                                    (self.path.parent, b"complete", False)])

    def test_publication_sync_failure_is_recoverable_without_overwrite(self):
        original = filesystem.publish
        def fail_after_publication(temporary, final):
            original(temporary, final)
            raise OSError("simulated directory sync failure")
        with patch.object(filesystem, "publish", side_effect=fail_after_publication), \
                self.assertRaises(BronzeFilesystemError):
            self.integrate()
        before = self.path.read_bytes()
        self.spy.register_integrated.assert_not_called()
        with patch.object(filesystem, "confirm_durable", wraps=filesystem.confirm_durable) as durable:
            result = self.integrate()
        durable.assert_called_once_with(self.path)
        self.assertFalse(result.created)
        self.assertEqual(self.path.read_bytes(), before)

    def test_unsupported_platform_does_not_register_even_existing_artifact(self):
        self.integrate()
        self.spy.reset_mock()
        with patch.object(filesystem, "_PLATFORM", "unsupported"), self.assertRaises(BronzeFilesystemError):
            self.integrate()
        self.spy.register_integrated.assert_not_called()

    def test_fresh_process_recovery_at_write_and_publication_boundaries(self):
        script = r'''
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "tests"))
from test_bronze import selected_source
from league_knowledge_platform import BronzeConfig, SQLiteSourceCatalog, integrate_selected_source
from league_knowledge_platform import _bronze_filesystem as fs
root, boundary = Path(sys.argv[1]), sys.argv[2]
original_stage, original_publish = fs.stage, fs.publish
if boundary == "during_write":
    def stage(directory, encoded_id, content):
        (directory / (".bronze-tmp-" + encoded_id + "-" + "a" * 32 + ".tmp")).write_bytes(content[:20])
        os._exit(71)
    fs.stage = stage
elif boundary == "before_publish":
    def publish(*args):
        os._exit(71)
    fs.publish = publish
elif boundary == "after_publish":
    def publish(*args):
        original_publish(*args)
        os._exit(71)
    fs.publish = publish
integrate_selected_source(selected_source(), catalog=SQLiteSourceCatalog(root / "catalog.sqlite3"), config=BronzeConfig(root / "bronze"))
'''
        for boundary in ("during_write", "before_publish", "after_publish"):
            with self.subTest(boundary=boundary), TemporaryDirectory() as root:
                root = Path(root)
                catalog = initialize_source_catalog(root / "catalog.sqlite3")
                config = BronzeConfig(root / "bronze")
                result = subprocess.run([sys.executable, "-c", script, str(root), boundary],
                                        capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 71, result.stderr.decode(errors="replace"))
                self.assertFalse(catalog.is_integrated("A"))
                final = canonical_bronze_path("A", config)
                before = final.read_bytes() if final.exists() else None
                self.assertEqual(final.exists(), boundary == "after_publish")
                recovered = subprocess.run([sys.executable, "-c", script, str(root), "retry"],
                                           capture_output=True, timeout=30)
                self.assertEqual(recovered.returncode, 0, recovered.stderr.decode(errors="replace"))
                self.assertTrue(catalog.is_integrated("A"))
                self.assertEqual(decode_bronze_artifact(final.read_bytes())["source"]["video_id"], "A")
                if before is not None:
                    self.assertEqual(final.read_bytes(), before)
                self.assertEqual(list(final.parent.iterdir()), [final])


if __name__ == "__main__":
    unittest.main()
