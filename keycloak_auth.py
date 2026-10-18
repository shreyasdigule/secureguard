"""
keycloak_auth.py — Keycloak access-token validation for the SecureGuard API.
"""

import hashlib
import json
import os
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

import jwt
from fastapi import HTTPException, Request, status

# Test key constants (used for hermetic test token validation)
# In production, these are never used — real keys come from Keycloak JWKS
TEST_KID = "secureguard-test-key"

TEST_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA5n2mKT8LnBQ8UcFuHWoE
MJs0Sgq374LtNp5Axonj+7vyKdRCzJ+fvAlWV31TR/YEzp/PUUF6WROLCj6mebZX
1HLY5EY0PVOSlRl9tdj1Dcc7JQJ36Z2eqOkIQOEHqbHna/IOsPLJjho4bQ0KsQdc
8DsTm16LsmswYuiM5geCihL4zAbyS0REpSwVQhkzo8JUWWY6VHoEukhpEEslCPFJ
uswWpMJw/UEUKPM4cHuivkBovVSd2AT5CeuFDfcNld90rp3xd2mVyDNi0EvtaXfG
vU45SlA0PHEOO7BK2c1/KElPRsT5nplxT57khGbwbsoVEZjLMglddLrteoEdVYpO
uQIDAQAB
-----END PUBLIC KEY-----"""

ISSUER = os.getenv("KEYCLOAK_ISSUER", "http://192.168.137.96:8080/realms/secureguard")
AUDIENCE = os.getenv("KEYCLOAK_AUDIENCE", "secureguard-api")
JWKS_URL = os.getenv("KEYCLOAK_JWKS_URL", f"{ISSUER}/protocol/openid-connect/certs")

MFA_FRESHNESS_WINDOW_SECONDS = int(os.getenv("SECUREGUARD_MFA_FRESHNESS", "300"))
TOKEN_MAX_AGE_SECONDS = int(os.getenv("SECUREGUARD_TOKEN_MAX_AGE", "900"))

def dual_control_required() -> bool:
    """Check if dual-control is required (reads env dynamically for testing)."""
    return os.getenv("SECUREGUARD_DUAL_CONTROL", "1") == "1"

def is_test_mode_enabled() -> bool:
    """Returns True only if SECUREGUARD_TEST_MODE is explicitly enabled."""
    return os.getenv("SECUREGUARD_TEST_MODE", "0") == "1"


_JWKS_CACHE: dict[str, Any] | None = None
_JWKS_EXPIRES_AT = 0.0
_JWKS_LOCK = threading.Lock()


def _compute_device_fingerprint(request: Optional[Request]) -> str:
    """Compute a device fingerprint from request headers."""
    if request is None:
        return "unknown"
    parts = [
        request.headers.get("user-agent", ""),
        request.headers.get("accept-language", ""),
        request.headers.get("accept-encoding", ""),
        request.client.host if request.client else "",
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class AuthContext:
    subject: str
    username: str
    roles: frozenset[str]
    mfa_verified: bool
    mfa_challenge_ts: Optional[int] = None
    device_fingerprint: str = "unknown"
    token_jti: Optional[str] = None
    token_issued_at: Optional[int] = None
    #: Absolute expiry taken from the JWT ``exp`` claim. The session countdown
    #: previously assumed a hardcoded 900s lifetime, which diverged from the
    #: real token lifetime whenever it differed.
    token_expires_at: Optional[float] = None
    second_supervisor_approved: bool = False

    def seconds_until_expiry(self, default_lifetime: int = TOKEN_MAX_AGE_SECONDS) -> float:
        """Seconds of session left, never negative."""
        if self.token_expires_at is not None:
            return max(0.0, self.token_expires_at - time.time())
        if self.token_issued_at is not None:
            return max(0.0, default_lifetime - (time.time() - self.token_issued_at))
        return 0.0

    @property
    def supervisor_approved(self) -> bool:
        return "supervisor" in self.roles

    def mfa_fresh(self, max_age_seconds: int = MFA_FRESHNESS_WINDOW_SECONDS) -> bool:
        if self.mfa_challenge_ts is None:
            return False
        return (time.time() - self.mfa_challenge_ts) < max_age_seconds

    def token_fresh(self, max_age_seconds: int = TOKEN_MAX_AGE_SECONDS) -> bool:
        if self.token_issued_at is None:
            return False
        return (time.time() - self.token_issued_at) < max_age_seconds

    def dual_control_satisfied(self) -> bool:
        if not dual_control_required():
            return True
        return self.supervisor_approved and self.second_supervisor_approved


def _load_jwks() -> dict[str, Any]:
    global _JWKS_CACHE, _JWKS_EXPIRES_AT
    now = time.monotonic()
    if _JWKS_CACHE and now < _JWKS_EXPIRES_AT:
        return _JWKS_CACHE
    with _JWKS_LOCK:
        if _JWKS_CACHE and time.monotonic() < _JWKS_EXPIRES_AT:
            return _JWKS_CACHE
        try:
            with urllib.request.urlopen(JWKS_URL, timeout=4) as response:
                _JWKS_CACHE = json.load(response)
            _JWKS_EXPIRES_AT = time.monotonic() + 300
            return _JWKS_CACHE
        except Exception as exc:
            # If cached JWKS exists even if expired, use it as fallback
            if _JWKS_CACHE:
                return _JWKS_CACHE
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Keycloak authentication server unreachable at {JWKS_URL}: {exc}",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc


def validate_access_token(token: str, request: Optional[Request] = None) -> AuthContext:
    """
    Validates a Keycloak RS256 Bearer access token.
    Extracts identity, roles, and MFA/AMR claims.
    """
    global _JWKS_CACHE
    try:
        header = jwt.get_unverified_header(token)
        key_id = header.get("kid")
        if not key_id:
            raise ValueError("Token header missing 'kid' (key ID)")

        # Handle hermetic test / offline tokens strictly when test mode is enabled
        if key_id == TEST_KID:
            if not is_test_mode_enabled():
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Forbidden: Test tokens are disabled in production environment",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            verification_key = TEST_PUBLIC_KEY
        else:
            jwks = _load_jwks()
            key_data = next((key for key in jwks.get("keys", []) if key.get("kid") == key_id), None)
            if not key_data:
                # Invalidate cache and retry once
                _JWKS_CACHE = None
                jwks = _load_jwks()
                key_data = next((key for key in jwks.get("keys", []) if key.get("kid") == key_id), None)
            if not key_data:
                raise ValueError(f"Signing key '{key_id}' not found in Keycloak JWKS")
            verification_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key_data))

        claims = jwt.decode(
            token,
            key=verification_key,
            algorithms=["RS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "iss", "sub"]},
        )

        roles = frozenset(claims.get("realm_access", {}).get("roles", []))
        authentication_methods = set(claims.get("amr", []))

        # Check standard AMR "otp" or "totp" or custom claims
        mfa_verified = bool(
            {"otp", "totp", "mfa"}.intersection(authentication_methods)
            or claims.get("otp_verified") is True
        )

        # Extract MFA challenge timestamp if present (custom claim)
        mfa_challenge_ts = claims.get("mfa_challenge_ts")
        if mfa_challenge_ts is not None:
            mfa_challenge_ts = int(mfa_challenge_ts)

        # Extract token JTI and issued-at
        token_jti = claims.get("jti")
        token_issued_at = claims.get("iat")
        token_exp = claims.get("exp")

        # Compute device fingerprint
        device_fingerprint = _compute_device_fingerprint(request)

        return AuthContext(
            subject=claims["sub"],
            username=claims.get("preferred_username", claims["sub"]),
            roles=roles,
            mfa_verified=mfa_verified,
            mfa_challenge_ts=mfa_challenge_ts,
            device_fingerprint=device_fingerprint,
token_jti=token_jti,
                token_issued_at=token_issued_at,
                token_expires_at=float(token_exp) if token_exp else None,
                second_supervisor_approved=False,  # Set via separate approval flow
        )
    except HTTPException:
        raise
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Keycloak access token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Keycloak token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
