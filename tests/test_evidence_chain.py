"""
test_evidence_chain.py - Tamper-evidence regression tests for the JSONL ledger.

The signature field is deliberately excluded from the canonical payload that the
chain hash and Ed25519 signature cover (``_EXCLUDED_FROM_CANONICAL``). That is
correct - the signature cannot hash itself - but it means deleting the signature
from a record leaves every hash internally consistent. The only remaining signal
is the structural invariant that unsigned records form a contiguous prefix at
the head of the ledger.

These tests pin that invariant. Without it, anyone with write access to the
ledger can rewrite any suffix, recompute the chain hashes, and strip the
signatures, and verification still reports the chain intact.
"""
import base64
import json

from evidence_log import _canonical, _compute_record_hash
from verify_log import _genesis_hash, verify_chain


def _build_chain(tmp_path, count=4):
    """Write a small self-consistent signed chain and return its records."""
    from crypto_audit import get_audit_signer_singleton

    signer = get_audit_signer_singleton()
    records = []
    previous = _genesis_hash()

    for index in range(count):
        payload = {
            "event_id": f"evt-{index}",
            "timestamp": 1700000000.0 + index,
            "subsystem": "Conveyor_Motor_01",
            "command": f"SET_SPEED = {400 + index} RPM",
            "user": "supervisor01",
            "final_decision": "ACCEPTED",
        }
        canonical = _canonical(payload)
        chain_hash = _compute_record_hash(canonical, previous)
        raw_signature = signer.sign((canonical + previous).encode("utf-8"))
        record = dict(payload)
        record["previous_record_hash"] = previous
        record["chain_hash"] = chain_hash
        record["signature"] = base64.b64encode(raw_signature).decode("ascii")
        records.append(record)
        previous = chain_hash

    path = tmp_path / "evidence_log.jsonl"
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
    )
    return path, records


def _write(path, records):
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
    )


def test_untouched_chain_verifies(tmp_path):
    path, _ = _build_chain(tmp_path)
    result = verify_chain(path)
    assert result.verified_ok == 4
    assert result.tampered is False
    assert result.unverifiable == 0


def test_signature_strip_from_signed_record_is_tampering(tmp_path):
    """The core bypass: `signature` is outside the signed payload."""
    path, records = _build_chain(tmp_path)
    records[-1]["signature"] = ""
    _write(path, records)

    result = verify_chain(path)
    assert result.tampered is True, "stripping a signature from a signed record passed"


def test_signature_strip_across_rewritten_suffix_is_tampering(tmp_path):
    path, records = _build_chain(tmp_path)
    for record in records[-2:]:
        record["signature"] = ""
    records[-1]["final_decision"] = "REJECTED_SAFETY"
    records[-1]["user"] = "attacker"
    _write(path, records)

    result = verify_chain(path)
    assert result.tampered is True


def test_payload_edit_with_valid_hash_structure_is_tampering(tmp_path):
    """Rewriting the payload must break the chain hash, not be waved through."""
    path, records = _build_chain(tmp_path)
    records[-1]["final_decision"] = "ACCEPTED"
    records[-1]["risk_score"] = 0.0
    _write(path, records)

    result = verify_chain(path)
    assert result.tampered is True


def test_erasing_all_signatures_is_never_an_all_clear(tmp_path):
    """Total signature erasure must not read as a verified chain."""
    path, records = _build_chain(tmp_path)
    for record in records:
        record["signature"] = ""
    _write(path, records)

    result = verify_chain(path)
    assert result.verified_ok == 0
    assert result.tampered is True or result.unverifiable > 0


def test_missing_key_reports_unverifiable_not_all_clear(tmp_path, monkeypatch):
    """Losing the signing key must not silently downgrade to "verified"."""
    import verify_log

    path, _ = _build_chain(tmp_path)
    monkeypatch.setattr(verify_log, "CRYPTO_AVAILABLE", False)

    result = verify_chain(path)
    assert result.verified_ok == 0
    assert result.signatures_checked is False
    assert result.unverifiable > 0
    assert "[OK] Chain VERIFIED" not in result.message