"""Offline persistence and failure tests using real temporary SQLite files."""

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from league_knowledge_platform import (
    SourceCatalogError,
    SQLiteSourceCatalog,
    initialize_source_catalog,
)


class SourceCatalogTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state" / "catalog.sqlite3"

    def catalog(self, **options):
        return initialize_source_catalog(self.path, **options)

    def execute(self, sql, parameters=()):
        with closing(sqlite3.connect(self.path)) as connection:
            result = connection.execute(sql, parameters).fetchall()
            connection.commit()
            return result

    def test_construction_does_not_create_files(self):
        SQLiteSourceCatalog(self.path)
        self.assertFalse(self.path.parent.exists())

    def test_explicit_initialization_creates_versioned_empty_catalog(self):
        catalog = self.catalog()
        self.assertEqual(catalog.load_integrated_ids(), frozenset())
        self.assertEqual(
            self.execute("SELECT component, version FROM schema_metadata"),
            [("source_catalog", 1)],
        )
        self.assertFalse(catalog.is_integrated("video-A"))

    def test_registration_survives_reopening_and_uses_case_sensitive_identity(self):
        catalog = self.catalog()
        self.assertTrue(catalog.register_integrated("Video-A"))
        reopened = SQLiteSourceCatalog(self.path)
        self.assertTrue(reopened.is_integrated("Video-A"))
        self.assertFalse(reopened.is_integrated("video-A"))
        self.assertTrue(reopened.register_integrated("video-A"))
        self.assertEqual(reopened.load_integrated_ids(), frozenset({"Video-A", "video-A"}))

    def test_repeated_registration_preserves_first_timestamp(self):
        catalog = self.catalog()
        self.assertTrue(catalog.register_integrated("video-A"))
        first = self.execute("SELECT video_id, registered_at_utc FROM integrated_sources")
        self.assertFalse(SQLiteSourceCatalog(self.path).register_integrated("video-A"))
        self.assertEqual(
            self.execute("SELECT video_id, registered_at_utc FROM integrated_sources"), first
        )
        self.assertTrue(first[0][1].endswith("+00:00"))

    def test_repeated_initialization_preserves_existing_catalog(self):
        self.catalog().register_integrated("video-A")
        first = self.execute("SELECT * FROM integrated_sources")
        reopened = self.catalog()
        self.assertEqual(reopened.load_integrated_ids(), frozenset({"video-A"}))
        self.assertEqual(self.execute("SELECT * FROM integrated_sources"), first)

    def test_snapshot_is_immutable_and_does_not_change_after_registration(self):
        catalog = self.catalog()
        catalog.register_integrated("video-A")
        snapshot = catalog.load_integrated_ids()
        catalog.register_integrated("video-B")
        self.assertIsInstance(snapshot, frozenset)
        self.assertEqual(snapshot, frozenset({"video-A"}))
        self.assertEqual(catalog.load_integrated_ids(), frozenset({"video-A", "video-B"}))

    def test_lookup_and_registration_do_not_initialize_missing_database(self):
        catalog = SQLiteSourceCatalog(self.path)
        for operation in (
            lambda: catalog.is_integrated("video-A"),
            catalog.load_integrated_ids,
            lambda: catalog.register_integrated("video-A"),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises(SourceCatalogError):
                    operation()
                self.assertFalse(self.path.exists())
        self.assertFalse(self.path.parent.exists())

    def test_read_connections_use_sqlite_read_only_mode(self):
        catalog = self.catalog()
        before = self.path.read_bytes()
        actual_connect = sqlite3.connect
        with patch("league_knowledge_platform.source_catalog.sqlite3.connect",
                   wraps=actual_connect) as connect:
            catalog.load_integrated_ids()
            catalog.is_integrated("video-A")
        self.assertEqual(connect.call_count, 2)
        for call in connect.call_args_list:
            self.assertTrue(call.args[0].endswith("?mode=ro"))
            self.assertTrue(call.kwargs["uri"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_uri_handles_spaces_and_hash_in_path(self):
        special = Path(self.directory.name) / "space # folder" / "catalog # one.sqlite3"
        catalog = initialize_source_catalog(special)
        catalog.register_integrated("video-A")
        self.assertTrue(SQLiteSourceCatalog(special).is_integrated("video-A"))

    def test_invalid_id_is_rejected_without_catalog_mutation(self):
        catalog = self.catalog()
        before = self.path.read_bytes()
        for video_id in ("", " ", "bad,id", "video-A\n", "https://youtube.com/v", None, 1):
            with self.subTest(video_id=video_id):
                with self.assertRaises(ValueError):
                    catalog.register_integrated(video_id)
                with self.assertRaises(ValueError):
                    catalog.is_integrated(video_id)
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_timeout_or_memory_path_is_rejected(self):
        for timeout in (0, -1, float("nan"), float("inf"), True, "5"):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                SQLiteSourceCatalog(self.path, timeout_seconds=timeout)
        with self.assertRaises(ValueError):
            SQLiteSourceCatalog(":memory:")
        self.assertFalse(self.path.exists())

    def test_corrupt_database_is_not_replaced_or_treated_as_empty(self):
        self.path.parent.mkdir()
        self.path.write_bytes(b"not a SQLite database")
        before = self.path.read_bytes()
        for operation in (
            self.catalog,
            SQLiteSourceCatalog(self.path).load_integrated_ids,
            lambda: SQLiteSourceCatalog(self.path).register_integrated("video-A"),
        ):
            with self.subTest(operation=operation), self.assertRaises(SourceCatalogError):
                operation()
        self.assertEqual(self.path.read_bytes(), before)

    def test_unsupported_version_preserves_existing_sources(self):
        catalog = self.catalog()
        catalog.register_integrated("video-A")
        self.execute("UPDATE schema_metadata SET version = 2 WHERE component = 'source_catalog'")
        before = self.path.read_bytes()
        for operation in (
            self.catalog,
            catalog.load_integrated_ids,
            lambda: catalog.register_integrated("video-B"),
        ):
            with self.subTest(operation=operation), self.assertRaises(SourceCatalogError):
                operation()
        self.assertEqual(self.path.read_bytes(), before)

    def test_unversioned_catalog_is_not_silently_adopted(self):
        self.path.parent.mkdir()
        self.execute("CREATE TABLE integrated_sources (video_id TEXT PRIMARY KEY)")
        self.execute("INSERT INTO integrated_sources VALUES ('video-A')")
        with self.assertRaises(SourceCatalogError):
            self.catalog()
        self.assertEqual(self.execute("SELECT * FROM integrated_sources"), [("video-A",)])
        self.assertEqual(self.execute(
            "SELECT name FROM sqlite_master WHERE name = 'schema_metadata'"), [])

    def test_missing_source_table_is_an_error_not_empty_history(self):
        catalog = self.catalog()
        self.execute("DROP TABLE integrated_sources")
        with self.assertRaises(SourceCatalogError):
            catalog.load_integrated_ids()
        with self.assertRaises(SourceCatalogError):
            self.catalog()

    def test_existing_other_component_metadata_is_preserved(self):
        self.path.parent.mkdir()
        self.execute("CREATE TABLE schema_metadata ("
                     "component TEXT NOT NULL PRIMARY KEY COLLATE BINARY, "
                     "version INTEGER NOT NULL CHECK(version > 0))")
        self.execute("INSERT INTO schema_metadata VALUES ('other_component', 7)")
        catalog = self.catalog()
        self.assertEqual(catalog.load_integrated_ids(), frozenset())
        self.assertEqual(self.execute(
            "SELECT version FROM schema_metadata WHERE component = 'other_component'"), [(7,)])

    def test_invalid_schema_shape_and_case_insensitive_primary_key_are_rejected(self):
        catalog = self.catalog()
        for definition in (
            "video_id TEXT PRIMARY KEY, registered_at_utc TEXT NOT NULL",
            "video_id TEXT NOT NULL PRIMARY KEY COLLATE NOCASE, registered_at_utc TEXT NOT NULL",
            "video_id TEXT NOT NULL PRIMARY KEY COLLATE BINARY, other_field TEXT NOT NULL",
        ):
            with self.subTest(definition=definition):
                self.execute("DROP TABLE integrated_sources")
                self.execute("CREATE TABLE integrated_sources (" + definition + ")")
                with self.assertRaises(SourceCatalogError):
                    catalog.load_integrated_ids()

    def test_invalid_stored_identity_is_not_silently_ignored(self):
        catalog = self.catalog()
        self.execute("INSERT INTO integrated_sources VALUES ('bad,id', '2026-01-01T00:00:00+00:00')")
        with self.assertRaises(SourceCatalogError):
            catalog.load_integrated_ids()

    def test_case_insensitive_component_metadata_is_not_adopted(self):
        self.path.parent.mkdir()
        self.execute("CREATE TABLE schema_metadata (component TEXT NOT NULL PRIMARY KEY "
                     "COLLATE NOCASE, version INTEGER NOT NULL)")
        self.execute("INSERT INTO schema_metadata VALUES ('Source_Catalog', 1)")
        with self.assertRaises(SourceCatalogError):
            self.catalog()
        self.assertEqual(self.execute("SELECT * FROM schema_metadata"), [("Source_Catalog", 1)])
        self.assertEqual(self.execute(
            "SELECT name FROM sqlite_master WHERE name = 'integrated_sources'"), [])

    def test_failed_registration_rolls_back_and_releases_connection(self):
        catalog = self.catalog()
        self.execute("CREATE TRIGGER reject_source AFTER INSERT ON integrated_sources "
                     "BEGIN SELECT RAISE(ABORT, 'simulated storage failure'); END")
        with self.assertRaises(SourceCatalogError):
            catalog.register_integrated("video-A")
        self.assertEqual(catalog.load_integrated_ids(), frozenset())
        self.execute("DROP TRIGGER reject_source")
        self.assertTrue(catalog.register_integrated("video-A"))

    def test_failed_commit_rolls_back_insert(self):
        catalog = self.catalog()
        actual_connect = sqlite3.connect

        class CommitFailure(sqlite3.Connection):
            def commit(self):
                raise sqlite3.OperationalError("simulated commit failure")

        def failing_connect(*args, **kwargs):
            return actual_connect(*args, factory=CommitFailure, **kwargs)

        with patch("league_knowledge_platform.source_catalog.sqlite3.connect",
                   side_effect=failing_connect):
            with self.assertRaises(SourceCatalogError):
                catalog.register_integrated("video-A")
        self.assertFalse(catalog.is_integrated("video-A"))
        self.assertTrue(catalog.register_integrated("video-A"))

    def test_failed_initial_migration_rolls_back_table_creation(self):
        self.path.parent.mkdir()
        self.execute("CREATE TABLE schema_metadata (component TEXT NOT NULL PRIMARY KEY, "
                     "version INTEGER NOT NULL)")
        self.execute("INSERT INTO schema_metadata VALUES ('other_component', 7)")
        self.execute("CREATE TRIGGER reject_version AFTER INSERT ON schema_metadata "
                     "BEGIN SELECT RAISE(ABORT, 'simulated migration failure'); END")
        with self.assertRaises(SourceCatalogError):
            self.catalog()
        self.assertEqual(self.execute(
            "SELECT name FROM sqlite_master WHERE name = 'integrated_sources'"), [])
        self.assertEqual(self.execute("SELECT * FROM schema_metadata"), [("other_component", 7)])

    def test_locked_database_fails_explicitly_without_registration(self):
        catalog = self.catalog(timeout_seconds=0.01)
        with closing(sqlite3.connect(self.path)) as other_writer:
            other_writer.execute("BEGIN IMMEDIATE")
            with self.assertRaises(SourceCatalogError):
                catalog.register_integrated("video-A")
            other_writer.rollback()
        self.assertEqual(catalog.load_integrated_ids(), frozenset())

    def test_old_sqlite_is_rejected_before_setup(self):
        with patch("league_knowledge_platform.source_catalog.sqlite3.sqlite_version_info",
                   (3, 23, 0)):
            with self.assertRaises(SourceCatalogError):
                self.catalog()
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
