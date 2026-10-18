"""
persistence.py — SQLite-backed persistence for SecureGuard.

Tables:
  - subsystem_state        : Real-time authorization state machine (original)
  - evidence_records       : Indexed forensic ledger mirror (Phase 2)

Production target is PostgreSQL/TimescaleDB; SQLite is the prototype backend.
Swapping the backend is a small change — the interface is intentionally minimal.

Note: Dual-control approvals now use separate dual_control.db with dual_control_store.py
for transactional locking and WAL mode.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app_paths import data_file

DB_PATH = data_file("secureguard.db")

#: How long a writer waits for another process's lock before giving up.
#:
#: Measured with one process holding an exclusive transaction on this file for
#: 8s while four others wrote through save_subsystem_state(): every one of the
#: four failed with ``sqlite3.OperationalError: database is locked`` after
#: ~7.4s. sqlite3.connect()'s default timeout is 5.0s, which is shorter than the
#: worst legitimate contention this file sees (a launch plus the REST gateway
#: both mirroring evidence). Losing a governance write because another process
#: held the file for a few seconds is a silent audit gap: the ledger record
#: lands, the mirror row does not, and nothing reports the difference.
#:
#: 10s matches dual_control_store's busy_timeout, so the two stores behave the
#: same way under contention.
BUSY_TIMEOUT_SECONDS = 10.0


def init_db():
    """Create all tables if they do not exist."""
    with _connect() as conn:
        # --- Subsystem state machine ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subsystem_state (
                subsystem_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                consecutive_low_residual INTEGER NOT NULL DEFAULT 0
            )
        """)

        # --- Forensic evidence ledger mirror (Phase 2) ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS evidence_records (
                event_id            TEXT PRIMARY KEY,
                timestamp           TEXT NOT NULL,
                user                TEXT NOT NULL,
                roles               TEXT NOT NULL,       -- JSON array
                mfa_verified        INTEGER NOT NULL,
                supervisor_approved INTEGER NOT NULL,
                command             TEXT NOT NULL,
                subsystem           TEXT NOT NULL,
                previous_state      TEXT NOT NULL,
                new_state           TEXT NOT NULL,
                residual            REAL,
                risk_score          REAL,
                risk_level          TEXT,
                final_decision      TEXT NOT NULL,
                rejection_reason    TEXT,
                xai_explanation     TEXT,
                previous_record_hash TEXT NOT NULL,
                chain_hash          TEXT NOT NULL
            )
        """)
        conn.commit()


@contextmanager
def _connect():
    # timeout= is the busy handler's own budget and PRAGMA busy_timeout is the
    # same setting stated where SQLite reports it; both are set because a caller
    # can inspect either and they must not disagree.
    conn = sqlite3.connect(DB_PATH, timeout=BUSY_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(f"PRAGMA busy_timeout = {int(BUSY_TIMEOUT_SECONDS * 1000)}")
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Subsystem state machine persistence (original)
# ---------------------------------------------------------------------------

def save_subsystem_state(subsystem_id: str, state: str, consecutive_low_residual: int):
    with _connect() as conn:
        conn.execute("""
            INSERT INTO subsystem_state (subsystem_id, state, consecutive_low_residual)
            VALUES (?, ?, ?)
            ON CONFLICT(subsystem_id) DO UPDATE SET
                state = excluded.state,
                consecutive_low_residual = excluded.consecutive_low_residual
        """, (subsystem_id, state, consecutive_low_residual))
        conn.commit()


def load_subsystem_state(subsystem_id: str):
    """Returns (state, consecutive_low_residual) or None if not found."""
    with _connect() as conn:
        cur = conn.execute(
            "SELECT state, consecutive_low_residual FROM subsystem_state WHERE subsystem_id = ?",
            (subsystem_id,),
        )
        row = cur.fetchone()
        return tuple(row) if row else None


def load_all_subsystem_states():
    with _connect() as conn:
        cur = conn.execute("SELECT subsystem_id, state, consecutive_low_residual FROM subsystem_state")
        return [tuple(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Forensic evidence records mirror (Phase 2)
# ---------------------------------------------------------------------------

def mirror_evidence_record(record_dict: dict):
    """
    Inserts or replaces a forensic evidence record into the SQLite mirror.
    Called by evidence_log.log_evidence() after every successful JSONL append.
    """
    with _connect() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO evidence_records (
                event_id, timestamp, user, roles, mfa_verified, supervisor_approved,
                command, subsystem, previous_state, new_state,
                residual, risk_score, risk_level,
                final_decision, rejection_reason, xai_explanation,
                previous_record_hash, chain_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record_dict["event_id"],
            record_dict["timestamp"],
            record_dict["user"],
            json.dumps(record_dict.get("roles", [])),
            int(record_dict.get("mfa_verified", False)),
            int(record_dict.get("supervisor_approved", False)),
            record_dict["command"],
            record_dict["subsystem"],
            record_dict["previous_state"],
            record_dict["new_state"],
            record_dict.get("residual"),
            record_dict.get("risk_score"),
            record_dict.get("risk_level"),
            record_dict["final_decision"],
            record_dict.get("rejection_reason", ""),
            record_dict.get("xai_explanation", ""),
            record_dict["previous_record_hash"],
            record_dict["chain_hash"],
        ))
        conn.commit()


def query_evidence(
    subsystem: str | None = None,
    user: str | None = None,
    final_decision: str | None = None,
    risk_level: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """
    Queries the evidence_records mirror with optional filters.
    Returns rows as list of dicts ordered by timestamp DESC.
    """
    clauses = []
    params: list = []
    if subsystem:
        clauses.append("subsystem = ?")
        params.append(subsystem)
    if user:
        clauses.append("user = ?")
        params.append(user)
    if final_decision:
        clauses.append("final_decision = ?")
        params.append(final_decision)
    if risk_level:
        clauses.append("risk_level = ?")
        params.append(risk_level)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    with _connect() as conn:
        cur = conn.execute(
            f"SELECT * FROM evidence_records {where} ORDER BY timestamp DESC LIMIT ?",
            params,
        )
        return [dict(row) for row in cur.fetchall()]


if __name__ == "__main__":
    init_db()
    save_subsystem_state("Test_Subsystem", "DEGRADED", 2)
    print("Saved. Reading back:")
    print(load_subsystem_state("Test_Subsystem"))
    print("All rows:")
    print(load_all_subsystem_states())
