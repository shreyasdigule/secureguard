import os
import time
import pytest
from fastapi import HTTPException, Request
import jwt

os.environ["SECUREGUARD_TEST_MODE"] = "1"

from keycloak_auth import validate_access_token, AuthContext
from tests.fixtures.test_keys import (
    create_test_token, 
    TEST_PRIVATE_KEY, 
    TEST_KID,
    expired_token,
    wrong_audience_token,
    wrong_issuer_token,
    missing_kid_token,
    rogue_key_token,
)


def test_valid_operator_token():
    token = create_test_token("operator01", ["operator"], mfa_verified=False)
    auth = validate_access_token(token, request=None)

    assert isinstance(auth, AuthContext)
    assert auth.username == "operator01"
    assert "operator" in auth.roles
    assert auth.mfa_verified is False
    assert auth.supervisor_approved is False
    assert auth.mfa_challenge_ts is None
    assert auth.device_fingerprint == "unknown"
    assert auth.token_jti is not None
    assert auth.token_issued_at is not None
    assert auth.second_supervisor_approved is False


def test_valid_supervisor_token_with_otp():
    token = create_test_token("supervisor01", ["supervisor", "operator"], mfa_verified=True)
    auth = validate_access_token(token, request=None)

    assert auth.username == "supervisor01"
    assert "supervisor" in auth.roles
    assert auth.mfa_verified is True
    assert auth.supervisor_approved is True
    assert auth.mfa_challenge_ts is not None  # Now included in test token
    assert auth.token_issued_at is not None


def test_valid_engineer_token():
    token = create_test_token("engineer01", ["engineer"], mfa_verified=False)
    auth = validate_access_token(token, request=None)

    assert auth.username == "engineer01"
    assert "engineer" in auth.roles
    assert auth.mfa_verified is False
    assert auth.supervisor_approved is False


def test_expired_token():
    token = expired_token("operator01", ["operator"])
    with pytest.raises(HTTPException) as exc_info:
        validate_access_token(token, request=None)
    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


def test_invalid_signature_rejected():
    # Sign with a different ad-hoc private key
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    rogue_key = rsa.generate_private_key(65537, 2048)
    rogue_pem = rogue_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()

    now = int(time.time())
    claims = {
        "exp": now + 3600,
        "iat": now,
        "iss": "http://192.168.137.96:8080/realms/secureguard",
        "aud": "secureguard-api",
        "sub": "rogue-user",
        "preferred_username": "attacker",
        "realm_access": {"roles": ["supervisor"]},
        "amr": ["pwd", "otp"],
    }
    headers = {"alg": "RS256", "typ": "JWT", "kid": "secureguard-test-key"}
    forged_token = jwt.encode(claims, rogue_pem, algorithm="RS256", headers=headers)

    with pytest.raises(HTTPException) as exc_info:
        validate_access_token(forged_token, request=None)
    assert exc_info.value.status_code == 401
    assert "signature" in exc_info.value.detail.lower() or "invalid" in exc_info.value.detail.lower()


def test_wrong_audience_rejected():
    token = wrong_audience_token("operator01", ["operator"])
    with pytest.raises(HTTPException) as exc_info:
        validate_access_token(token, request=None)
    assert exc_info.value.status_code == 401
    assert "audience" in exc_info.value.detail.lower() or "invalid" in exc_info.value.detail.lower()


def test_wrong_issuer_rejected():
    token = wrong_issuer_token("operator01", ["operator"])
    with pytest.raises(HTTPException) as exc_info:
        validate_access_token(token, request=None)
    assert exc_info.value.status_code == 401
    assert "issuer" in exc_info.value.detail.lower() or "invalid" in exc_info.value.detail.lower()


def test_missing_kid_rejected():
    token = missing_kid_token("operator01", ["operator"])
    with pytest.raises(HTTPException) as exc_info:
        validate_access_token(token, request=None)
    assert exc_info.value.status_code == 401


def test_test_token_rejected_in_production_mode():
    """When SECUREGUARD_TEST_MODE is disabled, test tokens must be rejected as forbidden."""
    os.environ["SECUREGUARD_TEST_MODE"] = "0"
    try:
        token = create_test_token("operator01", ["operator"])
        with pytest.raises(HTTPException) as exc_info:
            validate_access_token(token, request=None)
        assert exc_info.value.status_code == 401
        assert "disabled in production" in exc_info.value.detail.lower()
    finally:
        os.environ["SECUREGUARD_TEST_MODE"] = "1"


def test_mfa_fresh_check():
    """Test mfa_fresh method behavior."""
    from keycloak_auth import AuthContext
    import time
    
    # No MFA challenge timestamp
    auth = AuthContext(
        subject="sub-test",
        username="test",
        roles=frozenset(["operator"]),
        mfa_verified=True,
        mfa_challenge_ts=None,
    )
    assert auth.mfa_fresh() is False
    
    # Old MFA challenge
    auth = AuthContext(
        subject="sub-test",
        username="test",
        roles=frozenset(["operator"]),
        mfa_verified=True,
        mfa_challenge_ts=int(time.time()) - 600,  # 10 minutes ago
    )
    assert auth.mfa_fresh() is False
    
    # Fresh MFA challenge
    auth = AuthContext(
        subject="sub-test",
        username="test",
        roles=frozenset(["operator"]),
        mfa_verified=True,
        mfa_challenge_ts=int(time.time()) - 60,  # 1 minute ago
    )
    assert auth.mfa_fresh() is True


def test_token_fresh_check():
    """Test token_fresh method behavior."""
    from keycloak_auth import AuthContext
    import time
    
    # No issued at
    auth = AuthContext(
        subject="sub-test",
        username="test",
        roles=frozenset(["operator"]),
        mfa_verified=False,
        token_issued_at=None,
    )
    assert auth.token_fresh() is False
    
    # Old token
    auth = AuthContext(
        subject="sub-test",
        username="test",
        roles=frozenset(["operator"]),
        mfa_verified=False,
        token_issued_at=int(time.time()) - 2000,  # 33 minutes ago
    )
    assert auth.token_fresh() is False
    
    # Fresh token
    auth = AuthContext(
        subject="sub-test",
        username="test",
        roles=frozenset(["operator"]),
        mfa_verified=False,
        token_issued_at=int(time.time()) - 60,  # 1 minute ago
    )
    assert auth.token_fresh() is True


def test_dual_control_satisfied():
    """Test dual_control_satisfied method behavior."""
    from keycloak_auth import AuthContext, dual_control_required
    import os
    
    # Dual control disabled
    os.environ["SECUREGUARD_DUAL_CONTROL"] = "0"
    auth = AuthContext(
        subject="sub-test",
        username="test",
        roles=frozenset(["supervisor", "operator"]),
        mfa_verified=True,
        second_supervisor_approved=False,
    )
    assert auth.dual_control_satisfied() is True
    
    # Dual control enabled, but no second approval
    os.environ["SECUREGUARD_DUAL_CONTROL"] = "1"
    auth = AuthContext(
        subject="sub-test",
        username="test",
        roles=frozenset(["supervisor", "operator"]),
        mfa_verified=True,
        second_supervisor_approved=False,
    )
    assert auth.dual_control_satisfied() is False
    
    # Dual control enabled, with second approval
    auth = AuthContext(
        subject="sub-test",
        username="test",
        roles=frozenset(["supervisor", "operator"]),
        mfa_verified=True,
        second_supervisor_approved=True,
    )
    assert auth.dual_control_satisfied() is True
    
    # Not a supervisor
    auth = AuthContext(
        subject="sub-test",
        username="test",
        roles=frozenset(["operator"]),
        mfa_verified=True,
        second_supervisor_approved=True,
    )
    assert auth.dual_control_satisfied() is False
