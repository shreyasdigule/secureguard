"""
dual_control_store.py — Persistent Dual-Control Approval Store with Transactional Locking
Migrated from in-memory dictionary to SQLite with WAL mode and row-level locking.
"""

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app_paths import data_file
from typing import Optional, Dict, Any, List

# Database path
DB_PATH = data_file("dual_control.db")

# Global lock for SQLite operations
_db_lock = threading.RLock()

# Connection (single connection with WAL)
_connection: Optional[sqlite3.Connection] = None


def _get_connection() -> sqlite3.Connection:
    """Get or create the SQLite connection with WAL mode."""
    global _connection
    if _connection is None:
        _connection = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10.0)
        _connection.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrency
        _connection.execute("PRAGMA journal_mode=WAL")
        _connection.execute("PRAGMA synchronous=NORMAL")
        _connection.execute("PRAGMA busy_timeout=10000")  # 10 second busy timeout
        _connection.execute("PRAGMA foreign_keys=ON")
        _init_schema()
    return _connection


def _init_schema():
    """Initialize the dual-control approvals table."""
    conn = _get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dual_control_approvals (
            approval_key TEXT PRIMARY KEY,
            subsystem_id TEXT NOT NULL,
            target_username TEXT NOT NULL,
            action_description TEXT NOT NULL,
            first_approver TEXT NOT NULL,
            first_approved_at TEXT NOT NULL,
            second_approver TEXT,
            second_approved_at TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Index for faster lookups
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_subsystem_action 
        ON dual_control_approvals(subsystem_id, action_description)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_status 
        ON dual_control_approvals(status)
    """)
    conn.commit()


@contextmanager
def _transaction():
    """Context manager for atomic transactions with retry logic."""
    conn = _get_connection()
    max_retries = 3
    retry_delay = 0.1
    
    for attempt in range(max_retries):
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
            return
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() or "busy" in str(e).lower():
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
                    continue
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
    raise RuntimeError("Failed to acquire database lock after retries")


def _make_approval_key(subsystem_id: str, target_username: str, action_description: str) -> str:
    """Create a consistent approval key."""
    return f"{subsystem_id}:{target_username}:{action_description}"


def get_approval(key: str) -> Optional[Dict[str, Any]]:
    """Get approval by key."""
    conn = _get_connection()
    cursor = conn.execute(
        "SELECT * FROM dual_control_approvals WHERE approval_key = ?",
        (key,)
    )
    row = cursor.fetchone()
    if row:
        return dict(row)
    return None


def set_approval(key: str, approval: Dict[str, Any]) -> None:
    """Set or update approval with transactional safety."""
    # Ensure required fields
    required = ["subsystem_id", "target_username", "action_description", 
                "first_approver", "first_approved_at"]
    for field in required:
        if field not in approval:
            raise ValueError(f"Missing required field: {field}")
    
    subsystem_id = approval["subsystem_id"]
    target_username = approval["target_username"]
    action_description = approval["action_description"]
    first_approver = approval["first_approver"]
    first_approved_at = approval["first_approved_at"]
    second_approver = approval.get("second_approver")
    second_approved_at = approval.get("second_approved_at")
    
    key = f"{subsystem_id}:{target_username}:{action_description}"
    status = "satisfied" if second_approver else "pending"
    now = datetime.now(timezone.utc).isoformat()
    
    with _transaction() as conn:
        # Check if exists
        existing = conn.execute(
            "SELECT approval_key FROM dual_control_approvals WHERE approval_key = ?",
            (key,)
        ).fetchone()
        
        if existing:
            # Update existing
            conn.execute("""
                UPDATE dual_control_approvals SET
                    second_approver = ?,
                    second_approved_at = ?,
                    status = ?,
                    updated_at = ?
                WHERE approval_key = ?
            """, (second_approver, second_approved_at, status, now, key))
        else:
            # Insert new
            conn.execute("""
                INSERT INTO dual_control_approvals (
                    approval_key, subsystem_id, target_username, action_description,
                    first_approver, first_approved_at, second_approver, second_approved_at,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                key, subsystem_id, target_username, action_description,
                first_approver, first_approved_at, second_approver, second_approved_at,
                status, datetime.now(timezone.utc).isoformat(), now
            ))


def check_dual_control(subsystem_id: str, target_username: str, action_description: str) -> bool:
    """Check if dual-control approval exists and is satisfied."""
    key = f"{subsystem_id}:{target_username}:{action_description}"
    approval = get_approval(key)
    return approval is not None and approval.get("status") == "satisfied"


def get_approval_status(subsystem_id: str, target_username: str, action_description: str) -> Dict[str, Any]:
    """Get detailed approval status."""
    key = f"{subsystem_id}:{target_username}:{action_description}"
    approval = get_approval(key)
    
    if not approval:
        return {
            "status": "pending",
            "approvals": 0,
            "required": 2,
            "first_approver": None,
            "first_approved_at": None,
            "second_approver": None,
            "second_approved_at": None,
        }
    
    approvals = 1 + (1 if approval.get("second_approver") else 0)
    return {
        "status": approval.get("status", "pending"),
        "approvals": 1 + (1 if approval.get("second_approver") else 0),
        "required": 2,
        "first_approver": approval.get("first_approver"),
        "first_approved_at": approval.get("first_approved_at"),
        "second_approver": approval.get("second_approver"),
        "second_approved_at": approval.get("second_approved_at"),
    }


def clear_approval(key: str) -> bool:
    """Clear approval by key. Returns True if deleted."""
    conn = _get_connection()
    cursor = conn.execute(
        "DELETE FROM dual_control_approvals WHERE approval_key = ?",
        (key,)
    )
    conn.commit()
    return cursor.rowcount > 0


def clear_approval_by_components(subsystem_id: str, target_username: str, action_description: str) -> bool:
    """Clear approval by component parts."""
    key = f"{subsystem_id}:{target_username}:{action_description}"
    return clear_approval(key)


def get_all_approvals() -> Dict[str, Dict[str, Any]]:
    """Get all approvals (for backward compatibility and debugging)."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute("SELECT * FROM dual_control_approvals")
        rows = cursor.fetchall()
        return {row["approval_key"]: dict(row) for row in rows}
    finally:
        conn.close()


def clear_all() -> int:
    """Clear all approvals. Returns count deleted."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10.0)
    try:
        cursor = conn.execute("DELETE FROM dual_control_approvals")
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def get_pending_approvals() -> List[Dict[str, Any]]:
    """Get all pending (unsatisfied) approvals."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            "SELECT * FROM dual_control_approvals WHERE status = 'pending' ORDER BY created_at"
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_satisfied_approvals() -> List[Dict[str, Any]]:
    """Get all satisfied approvals."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            "SELECT * FROM dual_control_approvals WHERE status = 'satisfied' ORDER BY updated_at DESC"
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def cleanup_old_approvals(max_age_hours: int = 168) -> int:
    """Clean up approvals older than max_age_hours (default 1 week)."""
    cutoff = datetime.now(timezone.utc).timestamp() - (max_age_hours * 3600)
    cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat()
    
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10.0)
    try:
        cursor = conn.execute(
            "DELETE FROM dual_control_approvals WHERE updated_at < ? AND status = 'satisfied'",
            (cutoff_iso,)
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


# Backward compatibility: expose the in-memory dict interface
# This allows existing code to work without changes during transition
class _CompatDict(dict):
    """Dictionary-like interface that proxies to SQLite."""
    
    def __getitem__(self, key):
        val = get_approval(key)
        if val is None:
            raise KeyError(key)
        return val
    
    def __setitem__(self, key, value):
        # Parse key to extract components
        parts = key.split(":", 2)
        if len(parts) != 3:
            raise ValueError(f"Invalid key format: {key}")
        subsystem_id, target_username, action_description = parts
        value = dict(value)
        value["subsystem_id"] = subsystem_id
        value["target_username"] = target_username
        value["action_description"] = action_description
        set_approval(key, value)
    
    def __delitem__(self, key):
        if not clear_approval(key):
            raise KeyError(key)
    
    def __contains__(self, key):
        return get_approval(key) is not None
    
    def get(self, key, default=None):
        val = get_approval(key)
        return val if val is not None else default
    
    def items(self):
        all_approvals = get_all_approvals()
        return all_approvals.items()
    
    def clear(self):
        clear_all()


# Backward compatibility alias
_dual_control_approvals = _CompatDict()

# Initialize schema on import
_init_schema()
