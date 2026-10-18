"""
evidence_log.py — Cryptographically tamper-evident forensic evidence ledger.

Phase 2 upgrade:
  - Context-rich schema: user, roles, MFA/approval flags, full causal chain.
  - Ed25519 asymmetric signature chain:
        S_n = Sign_Ed25519(canonical(Record_n) || H_{n-1}, K_private)
        H_n = SHA256(canonical(Record_n) || H_{n-1})
    Every record seals the entire preceding history with asymmetric signature.
  - Genesis hash H_0 = SHA256("GENESIS") — deterministic root of the chain.
  - SQLite mirroring via persistence.py for fast dashboard queries.
  - Backward-compatible read_all_evidence() still works.
"""

import hashlib
import json
import os
import base64
import shutil
import time
import uuid
import logging
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import numpy as np

from persistence import mirror_evidence_record
from app_paths import data_file
from crypto_audit import (
    get_audit_signer_singleton, 
    verify_chain_signature,
    CRYPTO_AVAILABLE
)

# Persistent across launches. Path(__file__).parent pointed into PyInstaller's
# temp extraction dir, so the ledger was discarded on every exe exit and the
# Evidence Log tab always came up empty.
LOG_PATH = data_file("evidence_log.jsonl")

#: Name of the audit signing key inside the persistent data directory.
AUDIT_KEY_FILENAME = "audit_key.pem"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Audit signing key location
# ---------------------------------------------------------------------------
# WHY THIS IS HERE
#
# crypto_audit.get_audit_signer() wrote the Ed25519 key to
# ``Path.home() / ".secureguard" / "audit_key.pem"``, which is outside
# data_dir(). Two launches under different HOME values therefore generated two
# different keys, and verify_log verifies against the *current* launch's key.
# Proven with three separate processes against one SECUREGUARD_DATA_DIR: launch
# 2 read launch 1's two records as "Ed25519 signature verification failed" and
# reported "[TAMPER DETECTED] 2 of 4 records corrupted", and the count of
# false positives then grew with every launch. A record nobody touched was
# reported as tampered, which is precisely the failure a forensic ledger exists
# to prevent - and it is unrecoverable, because the key that signed the earlier
# records is gone.
#
# The key must travel WITH the ledger. It now resolves in this order:
#   1. ``AUDIT_KEY_PATH`` — explicit operator/deployment override.
#   2. ``SECUREGUARD_AUDIT_KEY_PATH`` — same intent, separate name so a
#      deployment cannot collide with an unrelated tool's variable.
#   3. ``data_dir()/audit_key.pem`` — beside evidence_log.jsonl, which is what
#      makes "same data directory" mean "same key" and therefore "same chain".
#
# An existing key at the old ~/.secureguard location is MIGRATED, not
# discarded, so upgrading does not orphan a live ledger. A legacy key that
# cannot be read is left alone and a warning is logged; it is never overwritten
# and never silently replaced, because replacing it would turn every record it
# signed into a false tamper report.
#
# This cannot disable verification. There is no branch that skips the
# signature check: a missing or unreadable key is a loud failure, not a
# downgrade to "unsigned".


def audit_key_path() -> Path:
    """
    Resolve the audit signing key path without touching the filesystem.

    Pure resolution so callers can decide for themselves whether a missing file
    means "create it" (the writer) or "we hold no key" (the verifier).
    """
    for variable in ("AUDIT_KEY_PATH", "SECUREGUARD_AUDIT_KEY_PATH"):
        override = os.getenv(variable)
        if override:
            return Path(override).expanduser().resolve()
    return data_file(AUDIT_KEY_FILENAME)


def _legacy_audit_key_path() -> Path:
    """Where the key used to live: HOME-dependent, hence the defect."""
    return Path.home() / ".secureguard" / AUDIT_KEY_FILENAME


def ensure_audit_key_file() -> Path:
    """
    Return the audit key path, creating or migrating the key if needed.

    Call this BEFORE ``get_audit_signer_singleton()`` so the signer is built
    from the resolved path. Raises OSError if the key cannot be established:
    an unauditable ledger is a hard failure, never a silent downgrade.
    """
    target = audit_key_path()
    if target.exists():
        return target

    target.parent.mkdir(parents=True, exist_ok=True)

    # Migrate a key from the old HOME-dependent location rather than orphaning
    # every record it already signed.
    legacy = _legacy_audit_key_path()
    if legacy.exists() and legacy.resolve() != target.resolve():
        try:
            shutil.copyfile(legacy, target)
            logger.warning(
                "Migrated audit signing key from %s to %s; records signed by the "
                "old key stay verifiable", legacy, target,
            )
            return target
        except OSError as exc:
            # Readable but not copyable: point at the old file rather than
            # generating a fresh key, which would falsely report the existing
            # ledger as tampered.
            logger.error(
                "Could not copy audit key %s -> %s (%s); continuing to use the "
                "original location", legacy, target, exc,
            )
            return legacy

    # Genuinely first run: let the signer generate, then persist where it will
    # be found next time. The signer is discarded here on purpose - log_evidence
    # calls the singleton itself once AUDIT_KEY_PATH is exported.
    from crypto_audit import SoftwareEd25519Signer
    signer = SoftwareEd25519Signer(key_id=os.getenv("AUDIT_KEY_ID", "audit-key-1"))
    payload = signer.export_private_key_pem()
    tmp = target.with_suffix(".pem.tmp")
    with open(tmp, "wb") as handle:
        handle.write(payload)
    os.replace(tmp, target)
    return target


def bind_audit_key() -> Path:
    """
    Resolve the key path and point ``AUDIT_KEY_PATH`` at it.

    ``crypto_audit.get_audit_signer()`` honours AUDIT_KEY_PATH only when the
    file already exists, so simply exporting the variable is not enough - hence
    ensure_audit_key_file() first. Returns the resolved path so the caller can
    log it.
    """
    path = ensure_audit_key_file()
    os.environ["AUDIT_KEY_PATH"] = str(path)
    return path


# ---------------------------------------------------------------------------
# Inter-process append lock
# ---------------------------------------------------------------------------
# The read-the-predecessor / append-the-successor pair has to be atomic ACROSS
# PROCESSES, not just across threads. Without this, two SecureGuard processes
# (the packaged exe plus the REST gateway, or two operators' consoles on one
# box) both read the same last chain_hash, both write records claiming it as
# their predecessor, and the ledger forks.
#
# Measured with four concurrent writer processes x 12 records: 44 records on
# disk instead of 48 (4 silently lost to interleaved appends) and 8 distinct
# duplicate-predecessor groups. verify_chain reported 44 of 44 records
# corrupted, first tampered at index #0 - a ledger that can never verify again.
#
# msvcrt.locking/fcntl.flock is used rather than a lock file with O_EXCL
# polling: the OS releases the handle when the process dies, so a crashed
# writer cannot leave a stale lock behind and wedge every future launch. The
# lock file is never deleted for the same reason.

_LOCK_FILENAME = "evidence_log.lock"
#: Generous, because the critical section is a tail read plus one line append.
#: Past it we proceed anyway: refusing to record governance events because
#: another process is slow is the worse failure, and the log records the stall.
_LOCK_TIMEOUT_SECONDS = 10.0
_LOCK_POLL_SECONDS = 0.02


@contextmanager
def _append_lock():
    """
    Hold an exclusive inter-process lock across read-predecessor + append.

    Yields even if the lock cannot be taken, so a lock implementation problem
    degrades to today's (fork-prone) behaviour with a loud warning rather than
    dropping forensic records on the floor.
    """
    lock_path = LOG_PATH.parent / _LOCK_FILENAME
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "a+b")
    except OSError as exc:
        logger.error("Evidence append lock unavailable (%s); proceeding unlocked", exc)
        yield
        return

    locked = False
    try:
        try:
            if os.name == "nt":
                import msvcrt
                deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
                while True:
                    try:
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        locked = True
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            break
                        time.sleep(_LOCK_POLL_SECONDS)
            else:  # pragma: no cover - POSIX only
                import fcntl
                deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
                while True:
                    try:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        locked = True
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            break
                        time.sleep(_LOCK_POLL_SECONDS)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Evidence append lock failed (%s); proceeding unlocked", exc)

        if not locked:
            logger.error(
                "Could not acquire %s within %.0fs; concurrent writers can fork "
                "the chain", lock_path, _LOCK_TIMEOUT_SECONDS,
            )
        yield
    finally:
        if locked:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:  # pragma: no cover - POSIX only
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:  # pragma: no cover - defensive
                pass
        handle.close()


class NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy types and dataclasses."""
    def default(self, obj):
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, (np.integer, np.int8, np.int16, np.int32, np.int64,
                            np.uint8, np.uint16, np.uint32, np.uint64)):
            return int(obj)
        if isinstance(obj, (np.floating, np.float16, np.float32, np.float64)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.datetime64):
            return str(obj)
        if is_dataclass(obj):
            return asdict(obj)
        return super().default(obj)


def _compute_record_hash(canonical_record: str, previous_hash: str) -> str:
    """H_n = SHA256(canonical_record || previous_hash) — for chain linking."""
    message = (canonical_record + previous_hash).encode("utf-8")
    return hashlib.sha256(message).hexdigest()


#: Fields excluded from the canonical form that gets hashed and signed.
#:
#: ``previous_record_hash`` MUST be excluded. It is empty when the canonical
#: string is first computed (before the predecessor is known) but populated by
#: the time the record is stored, so including it makes the stored hash
#: irrecoverable — every record then fails verification as "tampered".
_EXCLUDED_FROM_CANONICAL = ("chain_hash", "signature", "previous_record_hash")


def _canonical(record_dict: dict) -> str:
    """
    Produces a deterministic, sorted JSON string of the record (excluding
    the 'chain_hash', 'signature' and 'previous_record_hash' fields) for
    signing.

    Chain linkage is preserved because ``chain_hash`` is computed over
    ``canonical || previous_record_hash``, so the predecessor stays bound to
    the record without having to appear inside ``canonical`` itself.
    """
    signing_dict = {k: v for k, v in record_dict.items()
                    if k not in _EXCLUDED_FROM_CANONICAL}
    return json.dumps(signing_dict, sort_keys=True, separators=(",", ":"), cls=NumpyEncoder)


def _get_last_record_hashes() -> tuple[str, str]:
    """
    Reads the chain_hash and signature of the last record in the log file.
    Returns (chain_hash, signature) tuple.
    Returns genesis hash and empty signature if log is empty or missing.
    """
    genesis_hash = hashlib.sha256(b"GENESIS").hexdigest()

    if not LOG_PATH.exists():
        return genesis_hash, ""

    # Only the final record is needed, so read backwards from EOF instead of
    # parsing the whole ledger: this runs on every append, and a full scan made
    # a session of N writes cost O(N^2) JSON parsing.
    try:
        with open(LOG_PATH, "rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            window = min(end, 65536)
            while window <= end:
                f.seek(end - window)
                chunk = f.read(window)
                lines = [ln for ln in chunk.split(b"\n") if ln.strip()]
                # The first line of the chunk may be partial; only trust it if
                # we started at the beginning of the file.
                if window < end and lines:
                    lines = lines[1:]
                for raw in reversed(lines):
                    try:
                        rec = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    return rec.get("chain_hash", genesis_hash), rec.get("signature", "")
                window *= 4
    except OSError:
        return genesis_hash, ""

    return genesis_hash, ""


# ---------------------------------------------------------------------------
# Evidence Record Schema (Phase 2 — full causal chain with asymmetric signatures)
# ---------------------------------------------------------------------------

@dataclass
class EvidenceRecord:
    event_id: str
    timestamp: str
    # Identity context
    user: str                       # Username from JWT (e.g., "operator01")
    roles: list                     # Active roles (e.g., ["operator"])
    mfa_verified: bool              # True if AMR claim contained otp/totp/mfa
    supervisor_approved: bool       # True if "supervisor" role present
    device_fingerprint: str         # SHA256 hash of client headers
    token_jti: Optional[str]        # JWT ID claim for token tracking
    dual_control_satisfied: bool    # True if dual-control approval obtained
    # Command
    command: str                    # e.g., "SET_SPEED = 500 RPM"
    subsystem: str                  # e.g., "Conveyor_Motor_01"
    # State machine
    previous_state: str             # NORMAL | DEGRADED | RESTRICTED | QUARANTINED
    new_state: str                  # Post-transition state
    # Digital twin & anomaly
    predicted_trajectory: dict
    observed_trajectory: dict
    residual: float                 # Normalised error 0.0–1.0+ 
    risk_score: Optional[float]     # 0–100
    risk_level: Optional[str]       # LOW | MEDIUM | HIGH | CRITICAL
    # Decision
    final_decision: str             # ACCEPTED | REJECTED_SAFETY | REJECTED_AUTH | BLOCKED_QUARANTINE
    rejection_reason: str           # Descriptive reason or safety violation text
    xai_explanation: str            # Causal attribution text
    # Tamper-evidence (asymmetric)
    previous_record_hash: str       # H_{n-1} = SHA256(canonical_{n-1} || H_{n-2})
    chain_hash: str                 # H_n = SHA256(canonical_n || H_{n-1})
    signature: str                  # Ed25519 signature of (canonical_n || H_{n-1}), base64
    key_id: str                     # Key identifier used for signing


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def log_evidence(
    subsystem: str,
    command: str,
    previous_state: str,
    predicted_trajectory: dict,
    observed_trajectory: dict,
    residual: float,
    risk_score: Optional[float],
    risk_level: Optional[str],
    new_state: str,
    authorization_path: str,
    xai_explanation: str,
    # Phase 2 additions — identity context
    user: str = "unknown",
    roles: Optional[list] = None,
    mfa_verified: bool = False,
    supervisor_approved: bool = False,
    device_fingerprint: str = "unknown",
    token_jti: Optional[str] = None,
    dual_control_satisfied: bool = False,
    final_decision: str = "ACCEPTED",
    rejection_reason: str = "",
) -> "EvidenceRecord":
    """
    Appends a tamper-evident, context-rich forensic record to the JSONL ledger
    and mirrors it to the SQLite evidence_records table.
    Uses Ed25519 asymmetric signatures for non-repudiation.
    """
    if roles is None:
        roles = []

    # Establish the key path BEFORE anything asks for a signer, and hold the
    # inter-process append lock across the whole read-predecessor / write-successor
    # pair. Doing either after the signer exists would leave the two processes
    # signing with different keys, and doing the lock after the predecessor read
    # would leave the window in which the chain forks.
    bind_audit_key()

    with _append_lock():
        # Single chain read per record: this used to be called three times, which
        # re-scanned the entire ledger each time and could interleave badly under
        # concurrent writers.
        previous_hash, _ = _get_last_record_hashes()

        record_dict: dict = {
            "event_id": str(uuid.uuid4())[:8],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user": user,
            "roles": roles,
            "mfa_verified": mfa_verified,
            "supervisor_approved": supervisor_approved,
            "device_fingerprint": device_fingerprint,
            "token_jti": token_jti,
            "dual_control_satisfied": dual_control_satisfied,
            "command": command,
            "subsystem": subsystem,
            "previous_state": previous_state,
            "new_state": new_state,
            "predicted_trajectory": predicted_trajectory,
            "observed_trajectory": observed_trajectory,
            "residual": residual,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "final_decision": final_decision,
            "rejection_reason": rejection_reason,
            "xai_explanation": xai_explanation,
            # Tamper-evidence fields (populated below)
            "previous_record_hash": "",
            "chain_hash": "",
            "signature": "",
            "key_id": "",
        }

        # Resolve the signing key BEFORE hashing. key_id is part of the canonical
        # payload, so it has to hold its final value first; populating it after the
        # hash was computed made every record unverifiable. Binding it also stops
        # an attacker re-labelling a record as signed by a different key.
        if CRYPTO_AVAILABLE:
            signer = get_audit_signer_singleton()
            record_dict["key_id"] = signer.get_key_id()
        else:
            record_dict["key_id"] = "none"

        # Bind the predecessor. Stored on the record, but excluded from the
        # canonical form because chain linkage is already carried by chain_hash.
        record_dict["previous_record_hash"] = previous_hash

        # Compute canonical representation (excludes chain_hash/signature/previous)
        canonical = _canonical(record_dict)

        # Compute chain hash: H_n = SHA256(canonical_n || H_{n-1})
        chain_hash = hashlib.sha256((canonical + previous_hash).encode("utf-8")).hexdigest()
        record_dict["chain_hash"] = chain_hash

        # Sign: S_n = Sign_Ed25519(canonical_n || H_{n-1}, K_private)
        if CRYPTO_AVAILABLE:
            message = (canonical + previous_hash).encode("utf-8")
            signature_bytes = signer.sign(message)
            record_dict["signature"] = base64.b64encode(signature_bytes).decode("ascii")
        else:
            # Fallback for environments without cryptography
            record_dict["signature"] = "UNSIGNED"

        record = EvidenceRecord(**record_dict)

        # Write to JSONL ledger. One write() call of one complete line: the
        # inter-process lock serialises writers, and a single append keeps the
        # record indivisible for readers that tail the file.
        line = json.dumps(asdict(record), cls=NumpyEncoder) + "\n"
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    # Mirror to SQLite for fast dashboard queries
    try:
        mirror_evidence_record(record_dict)
    except Exception:
        # Log write must never fail due to DB issues, but a silent mirror
        # failure means the Evidence Log tab can drift from the ledger.
        logger.error("SQLite evidence mirror failed", exc_info=True)

    return record


#: Public alias so verification tooling cannot drift from the writer's rules.
#: Any module recomputing chain hashes MUST use this exact function.
canonical_payload = _canonical


def rotate_ledger(reason: str = "manual rotation") -> Optional[str]:
    """
    Archive the current ledger and start a fresh chain.

    Records written by the historical writer hashed a canonical form that
    included fields which were still empty at hash time (``previous_record_hash``
    and ``key_id``). Those hashes cannot be recomputed, so such a ledger can
    never verify. Rotation preserves the data by moving it aside rather than
    deleting it.

    Returns the archive path, or None if there was nothing to rotate.
    """
    if not LOG_PATH.exists() or LOG_PATH.stat().st_size == 0:
        return None

    archive_dir = LOG_PATH.parent / "evidence_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = archive_dir / f"evidence_log_{stamp}.jsonl"

    counter = 1
    while target.exists():
        target = archive_dir / f"evidence_log_{stamp}_{counter}.jsonl"
        counter += 1

    # Same lock as an append. Renaming the file out from under a concurrent
    # writer is exactly the same lost-record / lost-predecessor race, and here
    # it would additionally strand a record in a file nobody will verify.
    with _append_lock():
        if not LOG_PATH.exists() or LOG_PATH.stat().st_size == 0:
            return None
        LOG_PATH.replace(target)

    with open(archive_dir / "ROTATION_LOG.txt", "a", encoding="utf-8") as f:
        f.write(
            f"{datetime.now(timezone.utc).isoformat()} archived -> {target.name}  "
            f"({reason})\n"
        )
    logger.warning("Evidence ledger rotated to %s (%s)", target, reason)
    return str(target)


def classify_decision(result) -> str:
    """Return the canonical forensic label for a :class:`CommandResult`.

    Both the PySide6 console and the REST gateway append to this one signed
    ledger, so the label must not depend on which entry point ran the command.

    ``safety_violations`` is consulted first because it is structured pipeline
    output. The reason string is only a fallback: the governance gate messages
    ("BLOCKED: requires fresh step-up MFA ...", "BLOCKED: subsystem is
    QUARANTINED ...") never mention "auth" or "role", so a substring test on
    those words alone files authorization and quarantine refusals under safety.
    """
    if getattr(result, "accepted", False):
        return "ACCEPTED"

    if getattr(result, "safety_violations", None):
        return "REJECTED_SAFETY"

    reason = str(getattr(result, "reason", "") or "").lower()
    if "quarantine" in reason or "quarantined" in reason:
        return "BLOCKED_QUARANTINE"
    if any(
        token in reason
        for token in ("mfa", "auth", "role", "dual-control", "dual control",
                      "supervisor approval", "not authenticated")
    ):
        return "REJECTED_AUTH"
    return "REJECTED"


def log_auth_rejection(
    subsystem: str,
    command: str,
    reason: str,
    user: str = "unauthenticated",
    roles: Optional[list] = None,
    device_fingerprint: str = "unknown",
) -> "EvidenceRecord":
    """
    Logs gateway/auth-level rejections that never reach pipeline.process_command().
    Fixes the forensic blackout identified in Phase 1.2.
    """
    return log_evidence(
        subsystem=subsystem,
        command=command,
        previous_state="UNKNOWN",
        predicted_trajectory={},
        observed_trajectory={},
        residual=-1.0,
        risk_score=None,
        risk_level=None,
        new_state="BLOCKED",
        authorization_path=reason,
        xai_explanation="",
        user=user,
        roles=roles or [],
        mfa_verified=False,
        supervisor_approved=False,
        device_fingerprint=device_fingerprint,
        token_jti=None,
        dual_control_satisfied=False,
        final_decision="REJECTED_AUTH",
        rejection_reason=reason,
    )


def read_all_evidence() -> list[dict]:
    """
    Returns all evidence records as a list of dicts (newest-first).

    Malformed lines are skipped and logged rather than raised: a single corrupt
    line used to abort the read and leave the dashboard Evidence Log tab empty.
    """
    if not LOG_PATH.exists():
        return []
    records: list[dict] = []
    skipped = 0
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                skipped += 1
                logger.error("Skipping malformed evidence line: %s", exc)
    if skipped:
        logger.error(
            "Evidence log contained %d unreadable line(s) out of %d",
            skipped, len(records) + skipped,
        )
    return list(reversed(records))


# ---------------------------------------------------------------------------
# Chain Verification
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Chain Verification
# ---------------------------------------------------------------------------
# verify_log is the single authoritative chain verifier. This module used to
# carry a second, independent implementation; it had drifted in two ways that
# matter forensically - it hardcoded LOG_PATH (so it could only ever inspect the
# default ledger, never an archive or a rotated file) and it treated unsigned
# records as benign wherever they appeared in the chain. Two verifiers that can
# disagree are worse than one, so this is now a thin delegation.


def verify_chain(verbose: bool = False, log_path=None):
    """Verify the evidence chain by delegating to ``verify_log.verify_chain``.

    Returns ``verify_log.VerificationResult``. Import is deferred because
    ``verify_log`` imports from this module, so a module-level import would be
    circular.
    """
    from verify_log import verify_chain as _verify_chain

    return _verify_chain(
        log_path=Path(log_path) if log_path is not None else LOG_PATH,
        verbose=verbose,
    )
