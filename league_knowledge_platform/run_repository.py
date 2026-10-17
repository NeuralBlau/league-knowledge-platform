"""Separate SQLite run progress, with immutable copied targets and short transactions."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
import math
from pathlib import Path
import sqlite3

from .defaults import MAX_TARGET_ATTEMPTS, RUN_STATE_TIMEOUT_SECONDS
from .models import ChampionCatalog, ChampionTarget
from .run_lock import execution_guard
from .run_models import (
    AcquisitionRun, RunNotFoundError, RunStage, RunStateError, RunStatus, RunSummary,
    RunTarget, RunTargetStatus, TargetFailure, TargetFailureKind, catalog_digest,
    require_run_id, require_utc,
)
from .selection_models import NoSelectionReason, SelectionMethod


def _values(enum):
    return ",".join("'" + value.value + "'" for value in enum)


_TABLES = {
    "schema_metadata": "CREATE TABLE schema_metadata ("
    "component TEXT NOT NULL PRIMARY KEY COLLATE BINARY, "
    "version INTEGER NOT NULL CHECK (version > 0))",
    "acquisition_runs": f"""CREATE TABLE acquisition_runs (
        run_id TEXT NOT NULL PRIMARY KEY COLLATE BINARY,
        status TEXT NOT NULL CHECK (status IN ({_values(RunStatus)})),
        max_target_attempts INTEGER NOT NULL CHECK (max_target_attempts = {MAX_TARGET_ATTEMPTS}),
        snapshot_target_count INTEGER NOT NULL CHECK (snapshot_target_count > 0),
        catalog_schema_version INTEGER NOT NULL,
        roster_version TEXT NOT NULL,
        catalog_generated_at_utc TEXT NOT NULL,
        source_provider TEXT NOT NULL,
        source_url TEXT NOT NULL,
        source_locale TEXT NOT NULL,
        snapshot_sha256 TEXT NOT NULL,
        started_at_utc TEXT NOT NULL,
        updated_at_utc TEXT NOT NULL,
        finished_at_utc TEXT,
        CHECK ((status IN ('COMPLETED','COMPLETED_WITH_FAILURES')) =
               (finished_at_utc IS NOT NULL))
    )""",
    "acquisition_run_targets": f"""CREATE TABLE acquisition_run_targets (
        run_id TEXT NOT NULL COLLATE BINARY REFERENCES acquisition_runs(run_id),
        champion_id TEXT NOT NULL COLLATE BINARY,
        champion_key TEXT NOT NULL COLLATE BINARY,
        champion_name TEXT NOT NULL,
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        status TEXT NOT NULL CHECK (status IN ({_values(RunTargetStatus)})),
        attempt_count INTEGER NOT NULL CHECK (attempt_count BETWEEN 0 AND {MAX_TARGET_ATTEMPTS}),
        selected_video_id TEXT,
        selection_method TEXT CHECK (selection_method IN ({_values(SelectionMethod)})),
        no_selection_reason TEXT CHECK (no_selection_reason IN ({_values(NoSelectionReason)})),
        failure_stage TEXT CHECK (failure_stage IN ({_values(RunStage)})),
        failure_kind TEXT CHECK (failure_kind IN ({_values(TargetFailureKind)})),
        first_started_at_utc TEXT,
        attempt_started_at_utc TEXT,
        updated_at_utc TEXT NOT NULL,
        finished_at_utc TEXT,
        PRIMARY KEY (run_id, champion_id),
        UNIQUE (run_id, ordinal), UNIQUE (run_id, champion_key),
        CHECK ((status = 'PENDING') = (attempt_count = 0)),
        CHECK ((status = 'PENDING') = (first_started_at_utc IS NULL)),
        CHECK ((status = 'PENDING') = (attempt_started_at_utc IS NULL)),
        CHECK ((status IN ('SELECTED','NO_SELECTION','FAILED')) = (finished_at_utc IS NOT NULL)),
        CHECK ((status = 'SELECTED') = (selected_video_id IS NOT NULL)),
        CHECK (selected_video_id IS NULL OR length(selected_video_id) > 0),
        CHECK ((status = 'SELECTED') = (selection_method IS NOT NULL)),
        CHECK ((status = 'NO_SELECTION') = (no_selection_reason IS NOT NULL)),
        CHECK ((status = 'FAILED') = (failure_stage IS NOT NULL)),
        CHECK ((status = 'FAILED') = (failure_kind IS NOT NULL))
    )""",
}
_TRIGGERS = {
    "run_context_immutable": """CREATE TRIGGER run_context_immutable BEFORE UPDATE OF
        run_id, max_target_attempts, snapshot_target_count, catalog_schema_version,
        roster_version, catalog_generated_at_utc, source_provider, source_url,
        source_locale, snapshot_sha256, started_at_utc ON acquisition_runs
        BEGIN SELECT RAISE(ABORT, 'Immutable run context'); END""",
    "run_target_immutable": """CREATE TRIGGER run_target_immutable BEFORE UPDATE OF
        run_id, champion_id, champion_key, champion_name, ordinal ON acquisition_run_targets
        BEGIN SELECT RAISE(ABORT, 'Immutable run target'); END""",
    "run_target_no_delete": """CREATE TRIGGER run_target_no_delete
        BEFORE DELETE ON acquisition_run_targets
        BEGIN SELECT RAISE(ABORT, 'Immutable run membership'); END""",
    "run_target_bounded_insert": """CREATE TRIGGER run_target_bounded_insert
        BEFORE INSERT ON acquisition_run_targets
        WHEN NEW.ordinal >= (SELECT snapshot_target_count FROM acquisition_runs
                             WHERE run_id = NEW.run_id)
        BEGIN SELECT RAISE(ABORT, 'Run target outside original snapshot'); END""",
}
_RUN_COLUMNS = (
    "run_id,status,max_target_attempts,snapshot_target_count,catalog_schema_version,"
    "roster_version,catalog_generated_at_utc,source_provider,source_url,source_locale,"
    "snapshot_sha256,started_at_utc,updated_at_utc,finished_at_utc"
)
_TARGET_COLUMNS = (
    "run_id,champion_id,champion_key,champion_name,ordinal,status,attempt_count,"
    "selected_video_id,selection_method,no_selection_reason,failure_stage,failure_kind,"
    "first_started_at_utc,attempt_started_at_utc,updated_at_utc,finished_at_utc"
)


def _timestamp(text):
    if text is None:
        return None
    value = datetime.fromisoformat(text)
    require_utc(value)
    return value


def _target(row):
    return RunTarget(
        row["run_id"], ChampionTarget(row["champion_id"], row["champion_key"], row["champion_name"]),
        row["ordinal"], RunTargetStatus(row["status"]), row["attempt_count"], row["selected_video_id"],
        SelectionMethod(row["selection_method"]) if row["selection_method"] is not None else None,
        NoSelectionReason(row["no_selection_reason"]) if row["no_selection_reason"] is not None else None,
        TargetFailure(RunStage(row["failure_stage"]), TargetFailureKind(row["failure_kind"]))
        if row["failure_stage"] is not None else None,
        _timestamp(row["first_started_at_utc"]), _timestamp(row["attempt_started_at_utc"]),
        _timestamp(row["updated_at_utc"]), _timestamp(row["finished_at_utc"]),
    )


def _summary(run, targets):
    counts = {status: sum(t.status is status for t in targets) for status in RunTargetStatus}
    retryable = sum(t.status is RunTargetStatus.FAILED
                    and t.attempt_count < run.max_target_attempts for t in targets)
    return RunSummary(run.run_id, run.status, len(targets), counts[RunTargetStatus.PENDING],
                      counts[RunTargetStatus.RUNNING], counts[RunTargetStatus.SELECTED],
                      counts[RunTargetStatus.NO_SELECTION], counts[RunTargetStatus.FAILED], retryable)


class SQLiteRunRepository:
    """Construction has no filesystem effects. Initialize explicitly before service use.

    Mutation methods are used under execution_guard by the orchestration service.
    The guard serializes local invocations, while every SQL transaction closes before
    returning. Raw snapshots may contain stale ACTIVE until explicit recovery.
    """

    def __init__(self, path: str | Path, *, timeout_seconds: float = RUN_STATE_TIMEOUT_SECONDS):
        if str(path) == ":memory:":
            raise ValueError("Acquisition runs require a persistent file")
        if (type(timeout_seconds) not in (int, float)
                or not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
            raise ValueError("Run-state timeout must be finite and positive")
        self.path = Path(path).expanduser().resolve()
        self.timeout_seconds = timeout_seconds

    def execution_guard(self):
        return execution_guard(self.path)

    @contextmanager
    def _connection(self, mode):
        connection = sqlite3.connect(self.path.as_uri() + "?mode=" + mode, uri=True,
                                     timeout=self.timeout_seconds, isolation_level=None)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
            yield connection
        finally:
            try:
                if connection.in_transaction:
                    connection.rollback()
            finally:
                connection.close()

    def _require_schema(self, connection):
        objects = {row["name"]: (row["type"], " ".join(row["sql"].split()))
                   for row in connection.execute(
                       "SELECT name,type,sql FROM sqlite_master WHERE type IN ('table','trigger') "
                       "AND name NOT LIKE 'sqlite_%'")}
        expected = {name: ("table", " ".join(sql.split())) for name, sql in _TABLES.items()}
        expected.update({name: ("trigger", " ".join(sql.split()))
                         for name, sql in _TRIGGERS.items()})
        if objects != expected:
            raise RunStateError("Run-state schema is inconsistent or unsupported")
        versions = [tuple(row) for row in connection.execute(
            "SELECT component,version FROM schema_metadata")]
        if versions != [("acquisition_runs", 1)]:
            raise RunStateError("Run-state schema version is missing or unsupported")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RunStateError("Run-state foreign-key integrity failed")

    @contextmanager
    def _transaction(self, *, write=False):
        try:
            with self._connection("rw" if write else "ro") as connection:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                self._require_schema(connection)
                yield connection
                connection.commit()
        except (sqlite3.Error, OSError) as error:
            raise RunStateError("Cannot access acquisition run state safely") from error

    def initialize(self):
        """Create only this component's separate schema, or validate existing version 1."""
        with self.execution_guard():
            try:
                with self._connection("rwc") as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    present = connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
                    ).fetchone()
                    if present is None:
                        for sql in (*_TABLES.values(), *_TRIGGERS.values()):
                            connection.execute(sql)
                        connection.execute("INSERT INTO schema_metadata VALUES ('acquisition_runs',1)")
                    self._require_schema(connection)
                    connection.commit()
            except (sqlite3.Error, OSError) as error:
                raise RunStateError("Cannot initialize acquisition run state") from error

    def _load(self, connection, run_id):
        row = connection.execute("SELECT " + _RUN_COLUMNS
                                 + " FROM acquisition_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise RunNotFoundError("The requested acquisition run does not exist")
        try:
            targets = tuple(_target(t) for t in connection.execute(
                "SELECT " + _TARGET_COLUMNS + " FROM acquisition_run_targets "
                "WHERE run_id=? ORDER BY ordinal", (run_id,)))
            if (len(targets) != row["snapshot_target_count"]
                    or tuple(t.ordinal for t in targets) != tuple(range(len(targets)))):
                raise ValueError("Incomplete original target universe")
            catalog = ChampionCatalog(
                row["catalog_schema_version"], row["roster_version"],
                _timestamp(row["catalog_generated_at_utc"]), row["source_provider"],
                row["source_url"], row["source_locale"], tuple(t.target for t in targets),
            )
            run = AcquisitionRun(
                row["run_id"], RunStatus(row["status"]), catalog, row["snapshot_sha256"],
                row["max_target_attempts"], _timestamp(row["started_at_utc"]),
                _timestamp(row["updated_at_utc"]), _timestamp(row["finished_at_utc"]),
            )
            if any(t.status is RunTargetStatus.RUNNING for t in targets) and run.status is not RunStatus.ACTIVE:
                raise ValueError("Running work without an active invocation")
            if run.status in (RunStatus.COMPLETED, RunStatus.COMPLETED_WITH_FAILURES):
                expected = (RunStatus.COMPLETED_WITH_FAILURES
                            if any(t.status is RunTargetStatus.FAILED for t in targets)
                            else RunStatus.COMPLETED)
                if not all(t.terminal for t in targets) or run.status is not expected:
                    raise ValueError("Invalid completion accounting")
            return run, targets
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            raise RunStateError("Persisted run snapshot or progress is invalid") from error

    def get_run(self, run_id: str) -> AcquisitionRun:
        require_run_id(run_id)
        with self._transaction() as connection:
            return self._load(connection, run_id)[0]

    def list_targets(self, run_id: str) -> tuple[RunTarget, ...]:
        require_run_id(run_id)
        with self._transaction() as connection:
            return self._load(connection, run_id)[1]

    def summary(self, run_id: str) -> RunSummary:
        require_run_id(run_id)
        with self._transaction() as connection:
            return _summary(*self._load(connection, run_id))

    def create_run(self, run_id: str, catalog: ChampionCatalog, now: datetime):
        require_run_id(run_id)
        require_utc(now)
        if not isinstance(catalog, ChampionCatalog):
            raise ValueError("Run creation requires a complete validated catalog")
        catalog.__post_init__()
        timestamp = now.isoformat()
        with self._transaction(write=True) as connection:
            connection.execute("INSERT INTO acquisition_runs (" + _RUN_COLUMNS
                               + ") VALUES (" + ",".join("?" for _ in range(14)) + ")", (
                run_id, RunStatus.RESUMABLE.value, MAX_TARGET_ATTEMPTS, len(catalog.targets),
                catalog.schema_version, catalog.roster_version, catalog.generated_at_utc.isoformat(),
                catalog.source_provider, catalog.source_url, catalog.source_locale,
                catalog_digest(catalog), timestamp, timestamp, None,
            ))
            connection.executemany(
                "INSERT INTO acquisition_run_targets (run_id,champion_id,champion_key,champion_name,"
                "ordinal,status,attempt_count,updated_at_utc) VALUES (?,?,?,?,?,'PENDING',0,?)",
                ((run_id, t.id, t.key, t.name, i, timestamp) for i, t in enumerate(catalog.targets)),
            )
            self._load(connection, run_id)

    def _settle(self, connection, run, targets, now, *, closing):
        if run.status in (RunStatus.COMPLETED, RunStatus.COMPLETED_WITH_FAILURES):
            return
        if all(t.terminal for t in targets):
            status = (RunStatus.COMPLETED_WITH_FAILURES
                      if any(t.status is RunTargetStatus.FAILED for t in targets)
                      else RunStatus.COMPLETED)
            finished = now.isoformat()
        else:
            status = RunStatus.RESUMABLE if closing else RunStatus.ACTIVE
            finished = None
        connection.execute(
            "UPDATE acquisition_runs SET status=?,updated_at_utc=?,finished_at_utc=? WHERE run_id=?",
            (status.value, now.isoformat(), finished, run.run_id),
        )

    def recover_run(self, run_id: str, now: datetime) -> RunSummary:
        """Caller must hold the local guard; recovery never starts another attempt."""
        require_run_id(run_id)
        require_utc(now)
        with self._transaction(write=True) as connection:
            run, targets = self._load(connection, run_id)
            if run.status in (RunStatus.COMPLETED, RunStatus.COMPLETED_WITH_FAILURES):
                return _summary(run, targets)
            connection.execute(
                "UPDATE acquisition_run_targets SET status='FAILED',failure_stage='ORCHESTRATION',"
                "failure_kind='INTERRUPTED',updated_at_utc=?,finished_at_utc=? "
                "WHERE run_id=? AND status='RUNNING'", (now.isoformat(), now.isoformat(), run_id),
            )
            run, targets = self._load(connection, run_id)
            self._settle(connection, run, targets, now, closing=True)
            return _summary(*self._load(connection, run_id))

    def activate_run(self, run_id: str, now: datetime):
        require_run_id(run_id)
        require_utc(now)
        with self._transaction(write=True) as connection:
            run, targets = self._load(connection, run_id)
            if any(t.status is RunTargetStatus.RUNNING for t in targets):
                raise RunStateError("Recover interrupted targets before activating a run")
            self._settle(connection, run, targets, now, closing=False)

    def begin_attempt(self, run_id: str, champion_id: str, now: datetime) -> RunTarget:
        require_run_id(run_id)
        require_utc(now)
        with self._transaction(write=True) as connection:
            run, targets = self._load(connection, run_id)
            target = next((t for t in targets if t.target.id == champion_id), None)
            if (target is None or run.status is not RunStatus.ACTIVE or target.terminal
                    or target.status not in (RunTargetStatus.PENDING, RunTargetStatus.FAILED)
                    or target.attempt_count >= run.max_target_attempts
                    or any(t.status is RunTargetStatus.RUNNING for t in targets)):
                raise RunStateError("Target is not eligible for another sequential attempt")
            updated = replace(target, status=RunTargetStatus.RUNNING,
                              attempt_count=target.attempt_count + 1,
                              first_started_at_utc=target.first_started_at_utc or now,
                              attempt_started_at_utc=now, updated_at_utc=now,
                              finished_at_utc=None, failure=None)
            changed = connection.execute(
                "UPDATE acquisition_run_targets SET status='RUNNING',attempt_count=?,"
                "first_started_at_utc=?,attempt_started_at_utc=?,updated_at_utc=?,"
                "finished_at_utc=NULL,failure_stage=NULL,failure_kind=NULL "
                "WHERE run_id=? AND champion_id=? AND status=? AND attempt_count=?",
                (updated.attempt_count, updated.first_started_at_utc.isoformat(), now.isoformat(),
                 now.isoformat(), run_id, champion_id, target.status.value, target.attempt_count),
            ).rowcount
            if changed != 1:
                raise RunStateError("Attempt transition did not update exactly one target")
            connection.execute("UPDATE acquisition_runs SET updated_at_utc=? WHERE run_id=?",
                               (now.isoformat(), run_id))
            return updated

    def finish_attempt(
        self, run_id: str, champion_id: str, attempt_count: int, now: datetime, *,
        status: RunTargetStatus, selected_video_id: str | None = None,
        selection_method: SelectionMethod | None = None,
        no_selection_reason: NoSelectionReason | None = None, failure: TargetFailure | None = None,
    ):
        require_run_id(run_id)
        require_utc(now)
        if status not in (RunTargetStatus.SELECTED, RunTargetStatus.NO_SELECTION, RunTargetStatus.FAILED):
            raise ValueError("An attempt must finish with a typed outcome")
        with self._transaction(write=True) as connection:
            run, targets = self._load(connection, run_id)
            target = next((t for t in targets if t.target.id == champion_id), None)
            if (target is None or target.status is not RunTargetStatus.RUNNING
                    or type(attempt_count) is not int or target.attempt_count != attempt_count):
                raise RunStateError("Attempt result does not match running work")
            updated = replace(target, status=status, selected_video_id=selected_video_id,
                              selection_method=selection_method, no_selection_reason=no_selection_reason,
                              failure=failure, updated_at_utc=now, finished_at_utc=now)
            changed = connection.execute(
                "UPDATE acquisition_run_targets SET status=?,selected_video_id=?,selection_method=?,"
                "no_selection_reason=?,failure_stage=?,failure_kind=?,updated_at_utc=?,finished_at_utc=? "
                "WHERE run_id=? AND champion_id=? AND status='RUNNING' AND attempt_count=?",
                (updated.status.value, selected_video_id,
                 selection_method.value if selection_method is not None else None,
                 no_selection_reason.value if no_selection_reason is not None else None,
                 failure.stage.value if failure is not None else None,
                 failure.kind.value if failure is not None else None,
                 now.isoformat(), now.isoformat(), run_id, champion_id, attempt_count),
            ).rowcount
            if changed != 1:
                raise RunStateError("Result transition did not update exactly one target")
            self._settle(connection, *self._load(connection, run_id), now, closing=False)

    def finish_invocation(self, run_id: str, now: datetime) -> RunSummary:
        require_run_id(run_id)
        require_utc(now)
        with self._transaction(write=True) as connection:
            run, targets = self._load(connection, run_id)
            if any(t.status is RunTargetStatus.RUNNING for t in targets):
                raise RunStateError("Cannot finish an invocation with unrecorded work")
            self._settle(connection, run, targets, now, closing=True)
            return _summary(*self._load(connection, run_id))


def initialize_run_repository(
    path: str | Path, *, timeout_seconds: float = RUN_STATE_TIMEOUT_SECONDS,
) -> SQLiteRunRepository:
    repository = SQLiteRunRepository(path, timeout_seconds=timeout_seconds)
    repository.initialize()
    return repository
