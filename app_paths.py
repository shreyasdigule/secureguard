"""
app_paths.py — Persistent data directory resolution.

Why this module exists
----------------------
Every data path in this project used to be built as
``Path(__file__).parent / "<file>"``. That is correct when running from
source, but wrong in a PyInstaller one-file build: bundled modules resolve
``__file__`` inside the temporary extraction directory (``_MEIxxxxxx``) that
is deleted when the process exits.

The visible symptom was an Evidence Log that stayed empty: the ledger was
written into the temp folder and vanished with it, so every launch started a
brand new chain from GENESIS. The SQLite mirror and the dual-control store
were lost the same way, and because the Ed25519 signing key was generated
in-memory per process, signatures written by an earlier run could never be
verified by a later one.

Resolution order
----------------
1. ``SECUREGUARD_DATA_DIR`` environment variable, if set.
2. Directory containing the executable, when frozen (one-file or one-folder).
3. Directory containing this module (normal source run).
"""

import os
import sys
from pathlib import Path

#: Directory used for all mutable application state.
DATA_DIR: Path = None  # populated by data_dir()


def data_dir() -> Path:
    """Return the persistent data directory, creating it if necessary."""
    global DATA_DIR
    if DATA_DIR is not None:
        return DATA_DIR

    override = os.getenv("SECUREGUARD_DATA_DIR")
    if override:
        resolved = Path(override).expanduser().resolve()
    elif getattr(sys, "frozen", False):
        # sys.executable is the real .exe, not the temp extraction dir.
        resolved = Path(sys.executable).resolve().parent
    else:
        resolved = Path(__file__).resolve().parent

    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # Writability probe below decides whether this path is usable.

    # mkdir(exist_ok=True) does NOT raise when the directory already exists but
    # is not writable, so an exe deployed under C:\Program Files would sail past
    # a bare existence check and then fail inside sqlite3.connect on first write.
    if not _is_writable(resolved):
        # Read-only install directory: fall back to per-user storage rather
        # than crashing on first write.
        fallback = Path(os.getenv("LOCALAPPDATA", Path.home())) / "SecureGuard"
        fallback.mkdir(parents=True, exist_ok=True)
        if _is_writable(fallback):
            resolved = fallback
        else:  # pragma: no cover - defensive
            raise OSError(
                f"No writable data directory: neither {resolved} nor {fallback}"
            )

    DATA_DIR = resolved
    return resolved


def _is_writable(directory: Path) -> bool:
    """True when a file can actually be created inside ``directory``."""
    if not os.access(str(directory), os.W_OK):
        return False
    probe = directory / ".sg_write_probe"
    try:
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def data_file(name: str) -> Path:
    """Return a path inside the persistent data directory."""
    return data_dir() / name


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))