"""
test_keys.py — Test-only cryptographic fixtures for SecureGuard.

This module contains test-only keys and token generation utilities.
NEVER import this module in production code — it is only for tests.
"""

import os
import time
import jwt
from typing import Optional

# Force test mode
os.environ["SECUREGUARD_TEST_MODE"] = "1"

# Test key constants
TEST_KID = "secureguard-test-key"

# Test RSA 2048-bit key pair (for test tokens only)
# Generated once, committed to repo for reproducible tests
# NEVER use in production!
TEST_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDmfaYpPwucFDxR
wW4dagQwmzRKCrfvgu02nkDGieP7u/Ip1ELMn5+8CVZXfVNH9gTOn89RQXpZE4sK
PqZ5tlfUctjkRjQ9U5KVGX212PUNxzslAnfpnZ6o6QhA4Qepsedr8g6w8smOGjht
DQqxB1zwOxObXouyazBi6IzmB4KKEvjMBvJLRESlLBVCGTOjwlRZZjpUegS6SGkQ
SyUI8Um6zBakwnD9QRQo8zhwe6K+QGi9VJ3YBPkJ64UN9w2V33SunfF3aZXIM2LQ
S+1pd8a9TjlKUDQ8cQ47sErZzX8oSU9GxPmemXFPnuSEZvBuyhURmMsyCV10uu16
gR1Vik65AgMBAAECggEAFLrVxC1np6a5QxgcxXf4vv9ifUtH/jpeB9TFWiXiM4yU
i9cLl/g+R0zmr1E1+YmipovAe1wiexrzHR2D3vv7m7+liqhWv/JBg3fqsr170ryp
sNsvOjtjHulwhNdIV2aI/BAl6pu3bXilvQcYgFH7dZ62lXl0InyZ+jdUnsaroqvE
81AGt2fKu+NgSTwi2zHRuJd2BOKIr7knEgj3fz0a0zlZCtxo2C+tvh4wKt8LyDO3
NJFWoFVgtmsfdHdPgR1nqAgB5GZixEBuusXuPK/SQSqWKUWVF7vbr1xBBWekqYU+
cey9H3zy6b7SNB57RWlzqvtkGXnFP5wq3a0+BbjzhQKBgQDzvtn0zmuAly0xyjIB
Ec8Vb+S0JqI83BkJCGr/mdnavfvIwtQwJGFYUtrqjop4lXNTBxb/pi0qgsVtZaqD
fX9VyKzxlvlIp2GwsWbC6PHO3IlxS3azLisE2hU1skUy3In6tAckARV79K0K04X+
bttet+17+H+fYZj7B8o8AHquxQKBgQDyFDOwNseJ95oCgbYX8VSXfCsfNUdB0zm1
x4d6Y6HDH4IrR55JKQbpoiy/ldyBi4L7kzuDkDXFLVlenGBNZuplm8jkq6VKyany
AB3VbJilisIYjrVEEDKVIu+S/gEO6IUUF0GExzfTfc+CMw78+JJnlsPKcpS7YFN4
vHqssaufZQKBgC8iK8GEHROrqCiloc/FItdRYNdZVSwRn6G4iABPPupmrIag7ik1
D8Hlm8GZuLsioz9d8puTBc7fpM/HxhZRMUtkV9ULzb6351Mkqutr4j6PNOC8qAJ0
Hgt9JHbSt0DjlqbtIyhaMU5b/Q5H4vRVeYQyavD7F6q5U7zPP9MkgJTFAoGAXcFh
O3Ab291fcnUWNzOqVXkrokyaKm5KPZLnb4lCzzVWzrhQH3maScYbmp/J5QpJUnH1
bMDfclxb7n6V9aRUR8IMDjREMjDkduuAonYKsKKLBcPPhGrZjFUZgE6LzmBTmjJf
l7ModeqWAZEQzvzehuwnLDMwU1m9OleVE2lEVNkCgYEAs3ij3xxj0/HlYBNikBwX
3DY0jce80S8gMg+zYGxQKKaulnvVCwKDCE1+ayR5Jwz39Ts2zI3HnnmVT+ZnGpvs
CgAn7HeKwmOlvLuYJbH2rHROVxKi0S6Rebcij1koIIfBdV9a+PKKgKErn9a9+JE9
/p2hwEbKYno0uwmIm2rfC7g=
-----END PRIVATE KEY-----"""

TEST_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA5n2mKT8LnBQ8UcFuHWoE
MJs0Sgq374LtNp5Axonj+7vyKdRCzJ+fvAlWV31TR/YEzp/PUUF6WROLCj6mebZX
1HLY5EY0PVOSlRl9tdj1Dcc7JQJ36Z2eqOkIQOEHqbHna/IOsPLJjho4bQ0KsQdc
8DsTm16LsmswYuiM5geCihL4zAbyS0REpSwVQhkzo8JUWWY6VHoEukhpEEslCPFJ
uswWpMJw/UEUKPM4cHuivkBovVSd2AT5CeuFDfcNld90rp3xd2mVyDNi0EvtaXfG
vU45SlA0PHEOO7BK2c1/KElPRsT5nplxT57khGbwbsoVEZjLMglddLrteoEdVYpO
uQIDAQAB
-----END PUBLIC KEY-----"""

# Keycloak configuration for tests
KEYCLOAK_ISSUER = "http://192.168.137.96:8080/realms/secureguard"
KEYCLOAK_AUDIENCE = "secureguard-api"

# Test profiles
TEST_PROFILES = {
    "operator": {"username": "operator01", "roles": ["operator"], "mfa": False},
    "operator_mfa": {"username": "operator01", "roles": ["operator"], "mfa": True},
    "supervisor": {"username": "supervisor01", "roles": ["supervisor", "operator"], "mfa": True},
    "engineer": {"username": "engineer01", "roles": ["engineer"], "mfa": False},
    "auditor": {"username": "auditor01", "roles": ["auditor"], "mfa": False},
}


def create_test_token(
    username: str,
    roles: list[str],
    mfa_verified: bool = False,
    expires_in: int = 3600,
    issuer: str = KEYCLOAK_ISSUER,
    audience: str = KEYCLOAK_AUDIENCE,
) -> str:
    """
    Generates a cryptographically signed RS256 token using the internal test key.
    Enables hermetic testing and offline development without reaching out to Keycloak.
    
    WARNING: Only for testing. Uses hardcoded test key.
    """
    import uuid
    now = int(time.time())
    amr = ["pwd"]
    if mfa_verified:
        amr.append("otp")

    claims = {
        "exp": now + expires_in,
        "iat": now,
        "iss": issuer,
        "aud": audience,
        "sub": f"sub-{username}",
        "preferred_username": username,
        "realm_access": {"roles": roles},
        "amr": amr,
        "jti": str(uuid.uuid4()),
    }
    if mfa_verified:
        claims["mfa_challenge_ts"] = now
    headers = {
        "alg": "RS256",
        "typ": "JWT",
        "kid": TEST_KID,
    }
    return jwt.encode(claims, TEST_PRIVATE_KEY, algorithm="RS256", headers=headers)


def create_test_token_from_profile(profile_name: str, **overrides) -> str:
    """Create a test token from a predefined profile."""
    if profile_name not in TEST_PROFILES:
        raise ValueError(f"Unknown profile: {profile_name}. Available: {list(TEST_PROFILES.keys())}")
    
    profile = TEST_PROFILES[profile_name].copy()
    profile.update(overrides)
    
    return create_test_token(
        username=profile["username"],
        roles=profile["roles"],
        mfa_verified=profile["mfa"],
        **{k: v for k, v in overrides.items() if k not in ("username", "roles", "mfa")}
    )


# Quick token generators for common test scenarios
def operator_token(**kwargs) -> str:
    """Quick operator token (no MFA)."""
    return create_test_token_from_profile("operator", **kwargs)


def operator_mfa_token(**kwargs) -> str:
    """Quick operator token with MFA."""
    return create_test_token_from_profile("operator_mfa", **kwargs)


def supervisor_token(**kwargs) -> str:
    """Quick supervisor token (with MFA)."""
    return create_test_token_from_profile("supervisor", **kwargs)


def engineer_token(**kwargs) -> str:
    """Quick engineer token (no MFA)."""
    return create_test_token_from_profile("engineer", **kwargs)


def auditor_token(**kwargs) -> str:
    """Quick auditor token (no operational role, no MFA)."""
    return create_test_token_from_profile("auditor", **kwargs)


# Expired token for testing expiration handling
def expired_token(username: str = "operator01", roles: list[str] = None) -> str:
    """Create an expired token for testing expiration handling."""
    if roles is None:
        roles = ["operator"]
    return create_test_token(username, roles, mfa_verified=False, expires_in=-10)


# Token with wrong audience for testing audience validation
def wrong_audience_token(username: str = "operator01", roles: list[str] = None, audience: str = "malicious-client") -> str:
    """Create a token with wrong audience for testing validation."""
    if roles is None:
        roles = ["operator"]
    return create_test_token(username, roles, mfa_verified=False, audience=audience)


# Token with wrong issuer for testing issuer validation
def wrong_issuer_token(username: str = "operator01", roles: list[str] = None, issuer: str = "http://fake-keycloak:8080/realms/fake") -> str:
    """Create a token with wrong issuer for testing validation."""
    if roles is None:
        roles = ["operator"]
    return create_test_token(username, roles, mfa_verified=False, issuer=issuer)


# Token with missing KID for testing header validation
def missing_kid_token(username: str = "operator01", roles: list[str] = None) -> str:
    """Create a token with missing KID in header for testing validation."""
    if roles is None:
        roles = ["operator"]
    
    now = int(time.time())
    claims = {
        "exp": now + 3600,
        "iat": now,
        "iss": "http://192.168.137.96:8080/realms/secureguard",
        "aud": "secureguard-api",
        "sub": f"sub-{username}",
        "preferred_username": username,
        "realm_access": {"roles": roles},
    }
    # No KID in header
    headers = {"alg": "RS256", "typ": "JWT"}
    return jwt.encode(claims, TEST_PRIVATE_KEY, algorithm="RS256", headers=headers)


# Rogue key token for testing signature validation
def rogue_key_token(username: str = "rogue-user", roles: list[str] = None) -> str:
    """Create a token signed with a different key for testing signature validation."""
    if roles is None:
        roles = ["supervisor"]
    
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
        "sub": f"sub-{username}",
        "preferred_username": username,
        "realm_access": {"roles": roles},
        "amr": ["pwd", "otp"],
    }
    headers = {"alg": "RS256", "typ": "JWT", "kid": "secureguard-test-key"}
    return jwt.encode(claims, rogue_pem, algorithm="RS256", headers=headers)