"""Versioned SQLite database creation and migration."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

CURRENT_SCHEMA_VERSION = 6

_MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (
        """
        CREATE TABLE jobs (
            job_key TEXT PRIMARY KEY,
            company_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            external_job_id TEXT,
            canonical_url TEXT NOT NULL,
            fallback_fingerprint TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            description_hash TEXT,
            profile_version TEXT NOT NULL,
            prompt_version TEXT,
            evaluation_status TEXT NOT NULL
                CHECK (evaluation_status IN ('pending', 'completed', 'failed')),
            seniority_result_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (last_seen_at >= first_seen_at),
            CHECK (
                (evaluation_status = 'completed' AND seniority_result_json IS NOT NULL)
                OR evaluation_status != 'completed'
            )
        )
        """,
        "CREATE INDEX jobs_company_source_idx ON jobs (company_id, source_type)",
        "CREATE INDEX jobs_evaluation_status_idx ON jobs (evaluation_status)",
    ),
    2: ("ALTER TABLE jobs ADD COLUMN model_policy TEXT",),
    3: (
        """
        CREATE TABLE scan_runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL
                CHECK (status IN ('running', 'completed', 'partial', 'failed')),
            registry_version TEXT NOT NULL,
            profile_version TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            model_policy TEXT NOT NULL,
            metrics_json TEXT,
            CHECK (
                (status = 'running' AND completed_at IS NULL AND metrics_json IS NULL)
                OR (status != 'running' AND completed_at IS NOT NULL AND metrics_json IS NOT NULL)
            )
        )
        """,
        "CREATE INDEX scan_runs_started_at_idx ON scan_runs (started_at)",
    ),
    # Migration 4 -- job lifecycle and verdict columns (to_change.md 4.1, 4.2, 4.2a).
    #
    # Added as a numbered migration rather than by recreating the database, so the upgrade
    # path stays versioned and replayable on another machine. The 4.3 wipe of the existing
    # 859 rows is a separate, explicit step that runs *after* this lands: 9.10 requires the
    # wipe to follow both the normalization fix and the schema columns, or the store gets
    # re-keyed twice for no benefit.
    #
    # Everything is nullable or defaulted because SQLite cannot add a NOT NULL column
    # without a default, and because existing rows genuinely have no lifecycle history --
    # inventing one would be worse than admitting it is absent.
    4: (
        # 4.1: lifecycle state. Stored as current state, not history (4.2) -- with a
        # 3-absence close rule any gap a job survives is <= 2 days, so the overwritten
        # history is bounded and small.
        "ALTER TABLE jobs ADD COLUMN status TEXT NOT NULL DEFAULT 'active' "
        "CHECK (status IN ('active', 'closed'))",
        "ALTER TABLE jobs ADD COLUMN closed_at TEXT",
        # Needed as state, not history: tomorrow's run has to know today's count.
        "ALTER TABLE jobs ADD COLUMN consecutive_absences INTEGER NOT NULL DEFAULT 0",
        # The live-but-missing bucket runs on a different clock from plain absence (3.2).
        "ALTER TABLE jobs ADD COLUMN probe_state TEXT",
        "ALTER TABLE jobs ADD COLUMN live_but_missing_days INTEGER NOT NULL DEFAULT 0",
        # Guard 3 (3.3): a job needs >= 2 confirmed sightings before it may expire.
        "ALTER TABLE jobs ADD COLUMN sighting_count INTEGER NOT NULL DEFAULT 0",
        # 3.6: the feed sorts on when a job first reached a qualifying verdict, NOT on
        # first sighting. This is load-bearing for the recovered Google rows -- they carry
        # old first_seen_at values, so keying the feed on first sighting would mean the
        # ~78 rows stranded by the normalization bug never appear as new.
        "ALTER TABLE jobs ADD COLUMN verdict TEXT",
        "ALTER TABLE jobs ADD COLUMN verdict_at TEXT",
        # 3.5: store which basis the recency window used. Cannot be added retroactively,
        # and first_seen_at is not trustworthy until daily runs have been clean for a while.
        "ALTER TABLE jobs ADD COLUMN date_basis TEXT",
        # 4.1: the seniority prompt already returns this ("3+ years", "PhD + 4"). The model
        # is paying to produce it either way, and showing it tells you at a glance whether
        # an uncertain row is worth a click.
        "ALTER TABLE jobs ADD COLUMN required_experience TEXT",
        "CREATE INDEX jobs_status_idx ON jobs (status)",
        "CREATE INDEX jobs_verdict_at_idx ON jobs (verdict_at)",
    ),
    # Migration 5 -- description text and the two LLM judgments that were being thrown away.
    #
    # Until now only `verdict` survived the merged call, so the judgment that rejects ~59%
    # of evaluated jobs was the one judgment you could not ask "why?" about afterwards. The
    # model already produces a validated verbatim quote and a reason for all three
    # judgments and we were paying for them, so this is recovering output already bought.
    # Measured against 259 real responses: ~600-750 bytes per job, ~2.5MB across a full
    # 3,677-job scan. Nothing is backfillable -- the discarded text is gone.
    #
    # Deliberately no CHECK length bounds. docs/decisions.md D8 measured max evidence at 259
    # chars against a 500 cap with zero violations and deferred schema bounds; adding them
    # here would quietly reverse that without new evidence.
    5: (
        # The one genuinely large column. Written only for jobs that reach evaluation
        # (~3,677), never for all ~42,000 listings, and nulled by `state prune` once a job
        # has not been seen for a while. ~23kB each, so ~85MB for a first full scan.
        "ALTER TABLE jobs ADD COLUMN description TEXT",
        "ALTER TABLE jobs ADD COLUMN relevance_evidence TEXT",
        "ALTER TABLE jobs ADD COLUMN relevance_reason TEXT",
        # Nullable for a second reason beyond "old rows lack it": the merged call is asked
        # to judge location only when the deterministic filter could not resolve it, so a
        # NULL here legitimately means "never asked", not "asked and got nothing".
        "ALTER TABLE jobs ADD COLUMN location_evidence TEXT",
        "ALTER TABLE jobs ADD COLUMN location_reason TEXT",
    ),
    6: (
        """CREATE TABLE daily_batch (
            singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
            batch_id TEXT NOT NULL, admission_date TEXT NOT NULL,
            attempt_id TEXT NOT NULL, evaluation_config TEXT NOT NULL,
            discovery_config TEXT NOT NULL, force INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL, lifecycle_json TEXT
        )""",
        """CREATE TABLE batch_candidates (
            ordinal INTEGER PRIMARY KEY, job_key TEXT NOT NULL UNIQUE,
            payload_json TEXT NOT NULL, is_new INTEGER NOT NULL,
            fetch_count INTEGER NOT NULL DEFAULT 0,
            description_error TEXT, result_json TEXT,
            batch_singleton INTEGER NOT NULL DEFAULT 1 REFERENCES daily_batch(singleton)
                ON DELETE CASCADE
        )""",
        """CREATE TABLE evaluation_cache (
            fingerprint TEXT PRIMARY KEY, job_key TEXT NOT NULL,
            result_json TEXT NOT NULL
        )""",
        """CREATE TABLE llm_requests (
            request_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL,
            batch_date TEXT NOT NULL, requested_at TEXT NOT NULL,
            ordinal INTEGER NOT NULL, fingerprint TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('inflight', 'returned', 'consumed', 'unknown')),
            response_json TEXT, model_policy TEXT NOT NULL,
            input_tokens INTEGER, output_tokens INTEGER,
            rates_json TEXT, discarded_reason TEXT
        )""",
        "CREATE INDEX llm_requests_attempt_idx ON llm_requests(attempt_id, ordinal)",
        """CREATE TABLE daily_observations (
            job_key TEXT NOT NULL, observed_date TEXT NOT NULL,
            baseline_json TEXT NOT NULL, PRIMARY KEY(job_key, observed_date)
        )""",
        """CREATE TABLE daily_company_counts (
            company_id TEXT NOT NULL, observed_date TEXT NOT NULL,
            listing_count INTEGER NOT NULL, PRIMARY KEY(company_id, observed_date)
        )""",
    ),
}


def open_database(path: Path) -> sqlite3.Connection:
    """Open a local database with integrity-oriented connection settings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


@contextmanager
def migrated_database(path: Path) -> Iterator[sqlite3.Connection]:
    """Open, migrate, and close a database."""
    connection = open_database(path)
    try:
        migrate_database(connection)
        yield connection
    finally:
        connection.close()


def migrate_database(connection: sqlite3.Connection) -> int:
    """Apply every unapplied schema migration in one transaction."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied_versions = {
            int(row[0])
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        }
        unsupported = [version for version in applied_versions if version > CURRENT_SCHEMA_VERSION]
        if unsupported:
            newest = max(unsupported)
            raise ValueError(
                f"database schema version {newest} is newer than supported "
                f"version {CURRENT_SCHEMA_VERSION}"
            )
        missing_older = [
            version
            for version in range(1, max(applied_versions, default=0) + 1)
            if version not in applied_versions
        ]
        if missing_older:
            values = ", ".join(str(version) for version in missing_older)
            raise ValueError(f"database migration history has gaps: {values}")

        for version in range(1, CURRENT_SCHEMA_VERSION + 1):
            if version in applied_versions:
                continue
            for statement in _MIGRATIONS[version]:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, _utc_now_text()),
            )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return current_schema_version(connection)


def current_schema_version(connection: sqlite3.Connection) -> int:
    """Return the newest applied migration, or zero for an uninitialized database."""
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if exists is None:
        return 0
    row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    if row is None or row[0] is None:
        return 0
    return int(row[0])


def _utc_now_text() -> str:
    return datetime.now(UTC).isoformat()
