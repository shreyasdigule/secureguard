"""
verify_log.py — Cryptographic tamper-evidence verifier for the forensic ledger.

Phase 2.3 — Forensic Verification Tool (Updated for SHA-256 + Ed25519)

Usage (CLI):
    python verify_log.py                  # Verify default evidence_log.jsonl
    python verify_log.py --log path/to/evidence_log.jsonl
    python verify_log.py --verbose        # Print each record's hash state

API:
    from verify_log import verify_chain, VerificationResult
    result = verify_chain()
    if result.tampered:
        print(f"TAMPER DETECTED at record #{result.first_tampered_index}")

Verification algorithm (matches evidence_log.py):
    H_0 = SHA256(b"GENESIS")
    H_n = SHA256(canonical(Record_n) || H_{n-1})
    S_n = Sign_Ed25519(canonical(Record_n) || H_{n-1}, K_private)

    For each record:
      1. Recompute H_n from its fields and H_{n-1}.
      2. Compare with the stored chain_hash field.
      3. Verify that stored previous_record_hash == H_{n-1}.
      4. Verify Ed25519 signature against public key.
      5. Any mismatch → tamper detected at that index.
"""

import argparse
import base64
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

# Single source of truth for the canonical payload. Importing the writer's own
# function is what keeps verification from disagreeing with the ledger.
from evidence_log import canonical_payload

# Resolve through app_paths, never from __file__: in a PyInstaller one-file
# build __file__ points inside the temporary extraction directory, so the old
# default silently verified a non-existent ledger and reported "chain intact".
from app_paths import data_file

DEFAULT_LOG_PATH = data_file("evidence_log.jsonl")


# ---------------------------------------------------------------------------
# Internal hashing helpers (mirrors evidence_log.py)
# ---------------------------------------------------------------------------

def _genesis_hash() -> str:
    return hashlib.sha256(b"GENESIS").hexdigest()


def _canonical(record_dict: dict) -> str:
    """
    Deterministic canonical form used for hashing and signing.

    Delegates to evidence_log so this module cannot drift from the writer.
    The previous local copy excluded only ``chain_hash``/``signature`` while the
    writer also excluded ``previous_record_hash`` and populated ``key_id``
    before hashing, so every record produced by this file failed verification.
    """
    return canonical_payload(record_dict)


def _compute_chain_hash(canonical_record: str, previous_hash: str) -> str:
    message = (canonical_record + previous_hash).encode("utf-8")
    return hashlib.sha256(message).hexdigest()


# ---------------------------------------------------------------------------
# Verification Result
# ---------------------------------------------------------------------------

@dataclass
class RecordStatus:
    index: int
    event_id: str
    timestamp: str
    user: str
    subsystem: str
    final_decision: str
    expected_prev_hash: str
    stored_prev_hash: str
    expected_chain_hash: str
    stored_chain_hash: str
    signature_valid: bool
    ok: bool
    unverifiable: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass
class VerificationResult:
    log_path: str
    total_records: int
    verified_ok: int
    tampered: bool
    first_tampered_index: Optional[int]
    first_tampered_event_id: Optional[str]
    statuses: list[RecordStatus] = field(default_factory=list)
    message: str = ""
    unverifiable: int = 0
    signatures_checked: bool = False


# ---------------------------------------------------------------------------
# Core verification function
# ---------------------------------------------------------------------------

def verify_chain(
    log_path: Path = DEFAULT_LOG_PATH,
    verbose: bool = False,
) -> VerificationResult:
    """
    Walks the JSONL log from record 0 to N, recomputing and validating the
    SHA-256 hash chain and Ed25519 signatures. Returns a VerificationResult.
    """
    # Accept str as well as Path; callers reasonably pass either.
    log_path = Path(log_path)
    if not log_path.exists():
        return VerificationResult(
            log_path=str(log_path),
            total_records=0,
            verified_ok=0,
            tampered=False,
            first_tampered_index=None,
            first_tampered_event_id=None,
            message="Log file does not exist — nothing to verify.",
        )

    records: list[dict] = []
    with open(log_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                return VerificationResult(
                    log_path=str(log_path),
                    total_records=i + 1,
                    verified_ok=0,
                    tampered=True,
                    first_tampered_index=i,
                    first_tampered_event_id=None,
                    message=f"JSON parse error on line {i}: {exc}",
                )

    if not records:
        return VerificationResult(
            log_path=str(log_path),
            total_records=0,
            verified_ok=0,
            tampered=False,
            first_tampered_index=None,
            first_tampered_event_id=None,
            message="Log file is empty — chain is valid (genesis).",
        )

    # Get public key for verification.
    #
    # The key must be the one that signed THIS ledger, which is why it is
    # resolved through evidence_log.audit_key_path() (AUDIT_KEY_PATH, then
    # SECUREGUARD_AUDIT_KEY_PATH, then data_dir()/audit_key.pem) rather than
    # whatever the current HOME implies. Before that change the key lived at
    # ~/.secureguard/audit_key.pem, so two launches under different HOME values
    # signed and verified with different keys and every earlier record was
    # reported as tampered - proven across three processes, where launch 2 read
    # launch 1's two records as "[TAMPER DETECTED] 2 of 4 records corrupted".
    #
    # When the key cannot be established the chain hashes are still fully checked
    # and public_key_b64 stays None, so signed records become "unverifiable" -
    # reported as such and never as an all-clear.
    public_key_b64 = None
    if CRYPTO_AVAILABLE:
        try:
            from evidence_log import bind_audit_key
            bind_audit_key()
            from crypto_audit import get_audit_signer_singleton
            signer = get_audit_signer_singleton()
            public_key_b64 = base64.b64encode(signer.get_public_key_bytes()).decode("ascii")
        except Exception as exc:
            # Never fail open silently: an unavailable key means signatures
            # cannot be checked, which the caller must be told about.
            print(
                f"WARNING: audit signing key unavailable ({exc}); "
                f"signatures cannot be verified",
                file=sys.stderr,
            )

    statuses: list[RecordStatus] = []
    previous_hash = _genesis_hash()
    first_tampered_index: Optional[int] = None
    first_tampered_event_id: Optional[str] = None
    verified_ok = 0
    unverifiable_count = 0
    signed_era_started = False

    for idx, rec in enumerate(records):
        event_id = rec.get("event_id", f"<line-{idx}>")
        errors: list[str] = []
        signature_valid = True

        # Skip old-format records (pre-Phase2) that lack hash fields
        if "chain_hash" not in rec or "previous_record_hash" not in rec:
            # Treat as unverifiable but not tampered — advance genesis
            expected_chain = _compute_chain_hash(_canonical(rec), previous_hash)
            statuses.append(RecordStatus(
                index=idx,
                event_id=event_id,
                timestamp=rec.get("timestamp", ""),
                user=rec.get("user", ""),
                subsystem=rec.get("subsystem", ""),
                final_decision=rec.get("final_decision", rec.get("authorization_path", "")),
                expected_prev_hash=previous_hash,
                stored_prev_hash="N/A (legacy record)",
                expected_chain_hash=expected_chain,
                stored_chain_hash="N/A (legacy record)",
                signature_valid=False,
                ok=False,
                unverifiable=True,
                errors=[
                    "Unverifiable record: no chain_hash/previous_record_hash "
                    "fields, so its content cannot be authenticated"
                ],
            ))
            unverifiable_count += 1
            previous_hash = expected_chain
            continue

        stored_prev = rec.get("previous_record_hash", "")
        stored_chain = rec.get("chain_hash", "")
        stored_signature = rec.get("signature", "")
        signed = bool(stored_signature) and stored_signature != "UNSIGNED"

        # Signature/key_id are excluded from the canonical payload, so deleting
        # them leaves the hash chain internally consistent. The only signal that
        # a signed record was downgraded is that unsigned records are supposed
        # to form a contiguous prefix. Enforce that, or an attacker can strip
        # signatures from a rewritten suffix and verification stays green.
        if not signed and signed_era_started:
            errors.append(
                "Record lost its signature inside the signed era of the chain "
                "(unsigned records are only valid at the head of the ledger)"
            )

        # 1. Verify previous_record_hash matches what we expect
        if stored_prev != previous_hash:
            errors.append(
                f"previous_record_hash mismatch: expected {previous_hash[:16]}... "
                f"got {stored_prev[:16]}..."
            )

        # 2. Recompute chain_hash
        canonical = _canonical(rec)
        expected_chain = _compute_chain_hash(canonical, previous_hash)

        if stored_chain != expected_chain:
            errors.append(
                f"chain_hash mismatch: expected {expected_chain[:16]}... "
                f"got {stored_chain[:16]}..."
            )

        # 3. Verify Ed25519 signature if available
        unverifiable = False
        if public_key_b64 and signed:
            try:
                public_key_bytes = base64.b64decode(public_key_b64)
                public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
                message = (canonical + stored_prev).encode("utf-8")
                signature = base64.b64decode(stored_signature)
                public_key.verify(signature, message)
                signed_era_started = True
            except Exception:
                signature_valid = False
                errors.append("Ed25519 signature verification failed")
        elif not signed:
            # A stripped signature inside the signed era is tampering, not an
            # unverifiable record: the record was demonstrably signed once.
            signature_valid = False
            if not signed_era_started:
                unverifiable = True
                errors.append("Record has no valid signature")
        elif not CRYPTO_AVAILABLE:
            signature_valid = False
            unverifiable = True
            errors.append(
                "Cryptography library not available; signatures could not be verified"
            )
        elif not public_key_b64:
            # A signed record we hold no key for is unverifiable, NOT tampered.
            signature_valid = False
            unverifiable = True
            errors.append(
                "Audit signing key unavailable; signature could not be checked"
            )

        # Linkage and chain-hash integrity are verifiable without any key material, so
        # a failure there is always tampering - it must never be softened into
        # "unverifiable" just because the signature could not be checked.
        chain_intact = (stored_prev == previous_hash) and (stored_chain == expected_chain)

        ok = len(errors) == 0 and signature_valid
        if not chain_intact:
            if first_tampered_index is None:
                first_tampered_index = idx
                first_tampered_event_id = event_id
        elif unverifiable:
            # The hash chain holds but the signature could not be checked: the
            # record may be genuine, we simply cannot prove it with the material
            # on hand. Counted separately, never as an all-clear.
            unverifiable_count += 1
        elif ok:
            verified_ok += 1
        elif first_tampered_index is None:
            first_tampered_index = idx
            first_tampered_event_id = event_id

        statuses.append(RecordStatus(
            index=idx,
            event_id=event_id,
            timestamp=rec.get("timestamp", ""),
            user=rec.get("user", ""),
            subsystem=rec.get("subsystem", ""),
            final_decision=rec.get("final_decision", ""),
            expected_prev_hash=previous_hash,
            stored_prev_hash=stored_prev,
            expected_chain_hash=expected_chain,
            stored_chain_hash=stored_chain,
            signature_valid=signature_valid,
            ok=ok,
            unverifiable=unverifiable,
            errors=errors,
        ))

        # Advance chain using the EXPECTED hash (not the stored one) so we
        # can continue and count total tampered records rather than stopping.
        previous_hash = expected_chain

    tampered = first_tampered_index is not None
    total = len(records)

    if tampered:
        msg = (
            f"[TAMPER DETECTED] {total - verified_ok - unverifiable_count} of {total} "
            f"records corrupted. First tampered: record #{first_tampered_index} "
            f"(event_id={first_tampered_event_id})."
        )
    elif unverifiable_count:
        msg = (
            f"[INCOMPLETE] {verified_ok} of {total} records cryptographically "
            f"verified; {unverifiable_count} could not be verified with the "
            f"available key material. Not an all-clear."
        )
    else:
        msg = f"[OK] Chain VERIFIED -- all {total} records are intact and unmodified."

    return VerificationResult(
        log_path=str(log_path),
        total_records=total,
        verified_ok=verified_ok,
        tampered=tampered,
        first_tampered_index=first_tampered_index,
        first_tampered_event_id=first_tampered_event_id,
        statuses=statuses if verbose else [],
        message=msg,
        unverifiable=unverifiable_count,
        signatures_checked=bool(CRYPTO_AVAILABLE and public_key_b64),
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _cli():
    parser = argparse.ArgumentParser(
        description="SecureGuard Forensic Log Chain Verifier",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python verify_log.py
  python verify_log.py --log path/to/evidence_log.jsonl --verbose
        """,
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help="Path to evidence_log.jsonl (default: ./evidence_log.jsonl)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print the hash status of every individual record.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output result as JSON (for API/script consumers).",
    )
    args = parser.parse_args()

    result = verify_chain(log_path=args.log, verbose=args.verbose)

    if args.as_json:
        from dataclasses import asdict
        out = asdict(result)
        print(json.dumps(out, indent=2))
    else:
        print()
        print("=" * 60)
        print("  SecureGuard Forensic Chain Verifier")
        print("=" * 60)
        print(f"  Log file    : {result.log_path}")
        print(f"  Total records: {result.total_records}")
        print(f"  Verified OK  : {result.verified_ok}")
        print(f"  Status       : {result.message}")
        print("=" * 60)

        if args.verbose and result.statuses:
            print()
            print(f"  {'#':>4}  {'Event ID':>10}  {'OK':>6}  {'Sig':>6}  {'User':>12}  {'Subsystem':>16}  Decision")
            print("  " + "-" * 86)
            for s in result.statuses:
                ok_str = "[OK]" if s.ok else "[FAIL]"
                sig_str = "[OK]" if s.signature_valid else "[FAIL]"
                print(
                    f"  {s.index:>4}  {s.event_id:>10}  {ok_str:>6}  {sig_str:>6}  "
                    f"{s.user:>12}  {s.subsystem:>16}  {s.final_decision}"
                )
                for err in s.errors:
                    print(f"        -> ERROR: {err}")

    sys.exit(1 if result.tampered else 0)


if __name__ == "__main__":
    _cli()