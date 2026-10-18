# Test isolation for SecureGuard.
#
# pytest imports this file before any test module, so the env var is set and the
# cached module globals are reset BEFORE evidence_log / persistence /
# dual_control_store / verify_log resolve their data paths at import time.
# Without that, every test that builds a SecureGuardDashboard or submits a
# command through the pipeline appends a genuinely signed record to the
# production ledger in the repo root (evidence_log.jsonl, secureguard.db,
# dual_control.db) -- the exact contamination this file exists to prevent.
#
# Note on timing: a session-scoped autouse fixture body does NOT run before
# test-module collection. Test modules import evidence_log / persistence /
# dual_control_store / main at import time, and those modules cache their data
# paths as module globals on first call to app_paths.data_file(). So the env
# var has to be set in this module's top-level scope (which pytest executes
# first) rather than only inside the fixture. The fixture below is still the
# documented entry point and the cleanup mechanism; it also re-resolves the
# cached globals defensively in case anything resolved early.

import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root is available on sys.path
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import app_paths


def _reset_data_paths(temp_dir: str) -> None:
    """
    Point every module that caches a data path at the session temp directory.

    app_paths caches DATA_DIR as a module global on first call, and
    evidence_log / persistence / dual_control_store / verify_log each cache a
    derived path at import time. Setting the env var alone is not enough once
    any of them has resolved: the fixture must reset the cached globals too,
    and it must do so before the first import of those modules.
    """
    os.environ["SECUREGUARD_DATA_DIR"] = temp_dir

    # app_paths caches DATA_DIR; clear it so data_dir() re-resolves from the
    # env var (which is now set) instead of returning the stale repo-root path.
    app_paths.DATA_DIR = None

    import evidence_log
    import persistence
    import dual_control_store
    import verify_log

    evidence_log.LOG_PATH = app_paths.data_file("evidence_log.jsonl")
    persistence.DB_PATH = app_paths.data_file("secureguard.db")
    dual_control_store.DB_PATH = app_paths.data_file("dual_control.db")
    verify_log.DEFAULT_LOG_PATH = app_paths.data_file("evidence_log.jsonl")


def _seed_evidence() -> None:
    """
    The dashboard's Evidence Log tab renders ``read_all_evidence()`` and the
    compliance guard asserts it has rows. With an empty isolated ledger the tab
    renders nothing and the guard fails, so seed one canonical record into the
    temp ledger. This is test data, written to the temp dir, never to the repo.
    """
    from evidence_log import log_evidence

    log_evidence(
        subsystem="Conveyor_Motor_01",
        command="SET_SPEED = 500 RPM",
        previous_state="NORMAL",
        predicted_trajectory={"motor_speed_rpm": 500.0},
        observed_trajectory={"motor_speed_rpm": 500.0},
        residual=0.0,
        risk_score=0.0,
        risk_level="LOW",
        new_state="NORMAL",
        authorization_path="test-seed",
        xai_explanation="seed record for isolated test ledger",
        user="operator01",
        roles=["operator"],
        final_decision="ACCEPTED",
    )


def _close_open_databases() -> None:
    """
    Release module-level SQLite handles before the temp dir is removed.

    dual_control_store keeps one long-lived connection in a module global, and
    on Windows an open handle makes the file undeletable. shutil.rmtree with
    ignore_errors=True then deletes everything else, silently fails on the
    locked database, and every test run leaks a secureguard-test-* directory
    into TEMP.
    """
    import dual_control_store

    connection = getattr(dual_control_store, "_connection", None)
    if connection is not None:
        try:
            connection.close()
        except sqlite3.Error:
            pass
        dual_control_store._connection = None


# Top-level: runs at conftest import time, before any test module is collected.
# This is what makes the isolation real -- the env var exists before
# evidence_log / persistence / dual_control_store are first imported.
_TEMP_DIR = tempfile.mkdtemp(prefix="secureguard-test-")
_reset_data_paths(_TEMP_DIR)


@pytest.fixture(scope="session", autouse=True)
def isolated_data_dir():
    """One temp data dir for the whole session; production files never touched."""
    # Re-resolve defensively: if any module cached a repo-root path before this
    # point, correct it now. With the top-level call above this is a no-op, but
    # it keeps the fixture self-sufficient if conftest is ever reorganized.
    _reset_data_paths(_TEMP_DIR)
    _seed_evidence()
    yield _TEMP_DIR
    _close_open_databases()
    shutil.rmtree(_TEMP_DIR, ignore_errors=True)