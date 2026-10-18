"""
keycloak_client.py — Programmatic Keycloak Client & Token Helper for SecureGuard

Supports:
1. Live Direct Access Grants (password + OTP) against the Keycloak server.
2. Token refreshing and claim introspection.
3. Test token generation is now in tests/fixtures/test_keys.py for test mode only.
"""

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any, Optional
import jwt

KEYCLOAK_BASE_URL = os.getenv("KEYCLOAK_BASE_URL", "http://192.168.137.96:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "secureguard")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "secureguard-api")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "")
KEYCLOAK_ISSUER = os.getenv("KEYCLOAK_ISSUER", f"{KEYCLOAK_BASE_URL}/realms/{KEYCLOAK_REALM}")
KEYCLOAK_AUDIENCE = os.getenv("KEYCLOAK_AUDIENCE", "secureguard-api")


class KeycloakClient:
    """Client for authenticating against Keycloak OpenID Connect endpoints."""

    def __init__(
        self,
        base_url: str = KEYCLOAK_BASE_URL,
        realm: str = KEYCLOAK_REALM,
        client_id: str = KEYCLOAK_CLIENT_ID,
        client_secret: str = KEYCLOAK_CLIENT_SECRET,
    ):
        self.base_url = base_url.rstrip("/")
        self.realm = realm
        self.client_id = client_id
        self.client_secret = client_secret

    @property
    def token_endpoint(self) -> str:
        return f"{self.base_url}/realms/{self.realm}/protocol/openid-connect/token"

    @property
    def jwks_endpoint(self) -> str:
        return f"{self.base_url}/realms/{self.realm}/protocol/openid-connect/certs"

    def request_token(
        self,
        username: str,
        password: str,
        otp: Optional[str] = None,
        timeout: int = 5,
    ) -> dict[str, Any]:
        """
        Requests an access token using Direct Access Grants (Resource Owner Password).
        Pass otp/totp if MFA is configured for the account.
        """
        payload: dict[str, str] = {
            "grant_type": "password",
            "client_id": self.client_id,
            "username": username,
            "password": password,
        }
        if self.client_secret:
            payload["client_secret"] = self.client_secret
        if otp:
            payload["totp"] = otp
            payload["otp"] = otp

        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            self.token_endpoint,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Keycloak token request failed ({exc.code}): {error_body}") from exc
        except Exception as exc:
            raise RuntimeError(f"Could not connect to Keycloak at {self.token_endpoint}: {exc}") from exc

    def refresh_token(self, refresh_token: str, timeout: int = 5) -> dict[str, Any]:
        """Refreshes an access token using the refresh_token grant."""
        payload: dict[str, str] = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": refresh_token,
        }
        if self.client_secret:
            payload["client_secret"] = self.client_secret

        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            self.token_endpoint,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Keycloak refresh failed ({exc.code}): {error_body}") from exc
        except Exception as exc:
            raise RuntimeError(f"Could not connect to Keycloak at {self.token_endpoint}: {exc}") from exc

    @staticmethod
    def inspect_token_unverified(token: str) -> dict[str, Any]:
        """Decodes JWT claims without signature validation for UI inspection."""
        return jwt.decode(token, options={"verify_signature": False})


# Production mode: no test token generation here.
# Test token generation moved to tests/fixtures/test_keys.py
# Import from there when SECUREGUARD_TEST_MODE=1

def create_test_token(
    username: str,
    roles: list[str],
    mfa_verified: bool = False,
    expires_in: int = 3600,
    issuer: str = None,
    audience: str = None,
) -> str:
    """
    Test token generation - delegates to test fixtures in test mode.
    In production mode (SECUREGUARD_TEST_MODE=0), this raises an error.
    """
    if os.getenv("SECUREGUARD_TEST_MODE", "0") != "1":
        raise RuntimeError(
            "Test token generation not allowed in production mode. "
            "Set SECUREGUARD_TEST_MODE=1 for testing."
        )
    
    # Import from test fixtures (test mode only)
    from tests.fixtures.test_keys import create_test_token as _create_test_token
    
    return _create_test_token(
        username=username,
        roles=roles,
        mfa_verified=mfa_verified,
        expires_in=expires_in,
        issuer=issuer or KEYCLOAK_ISSUER,
        audience=audience or KEYCLOAK_AUDIENCE,
    )
