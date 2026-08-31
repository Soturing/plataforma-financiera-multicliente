from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import jwt
from jwt import PyJWKClient

from app.security.models import AuthLevel


ALLOWED_ASYMMETRIC_ALGORITHMS = frozenset({"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"})
MAX_BEARER_TOKEN_LENGTH = 16_384


class OIDCConfigurationError(RuntimeError):
    pass


class OIDCVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class OIDCPrincipal:
    subject: str
    provider_session_id: str
    authenticated_at: datetime
    auth_level: AuthLevel


class OIDCVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str,
        algorithms: tuple[str, ...] = ("RS256",),
        auth_level_claim: str | None = None,
    ) -> None:
        _require_https("issuer", issuer)
        _require_https("jwks_url", jwks_url)
        if not audience.strip():
            raise OIDCConfigurationError("OIDC audience is required")
        if not algorithms or not set(algorithms).issubset(ALLOWED_ASYMMETRIC_ALGORITHMS):
            raise OIDCConfigurationError("Only an explicit asymmetric JWT algorithm allow-list is accepted")
        self.issuer = issuer
        self.audience = audience
        self.algorithms = algorithms
        self.auth_level_claim = auth_level_claim
        self.jwks_client = PyJWKClient(jwks_url, cache_keys=True)

    def verify(self, token: str) -> OIDCPrincipal:
        if not token or len(token) > MAX_BEARER_TOKEN_LENGTH:
            raise OIDCVerificationError("Invalid bearer token")
        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=list(self.algorithms),
                audience=self.audience,
                issuer=self.issuer,
                options={
                    "require": ["sub", "iss", "aud", "exp", "iat", "auth_time", "sid"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
        except jwt.PyJWTError as exc:
            raise OIDCVerificationError("Invalid bearer token") from exc

        subject = _bounded_claim(claims, "sub", 500)
        provider_session_id = _bounded_claim(claims, "sid", 500)
        authenticated_at = _numeric_date(claims, "auth_time")
        issued_at = _numeric_date(claims, "iat")
        if authenticated_at > issued_at:
            raise OIDCVerificationError("Invalid bearer token")
        auth_level = _resolve_auth_level(claims, self.auth_level_claim)
        return OIDCPrincipal(
            subject=subject,
            provider_session_id=provider_session_id,
            authenticated_at=authenticated_at,
            auth_level=auth_level,
        )


def _require_https(name: str, value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise OIDCConfigurationError(f"{name} must be an HTTPS URL without embedded credentials")


def _bounded_claim(claims: dict[str, Any], name: str, maximum: int) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise OIDCVerificationError("Invalid bearer token")
    return value


def _numeric_date(claims: dict[str, Any], name: str) -> datetime:
    value = claims.get(name)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise OIDCVerificationError("Invalid bearer token")
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise OIDCVerificationError("Invalid bearer token") from exc


def _resolve_auth_level(claims: dict[str, Any], claim_name: str | None) -> AuthLevel:
    if claim_name:
        explicit = claims.get(claim_name)
        mapping = {
            "FEDERATED": AuthLevel.FEDERATED,
            "PASSKEY": AuthLevel.PASSKEY,
            "HARDWARE_KEY": AuthLevel.HARDWARE_KEY,
        }
        if explicit in mapping:
            return mapping[explicit]

    amr = claims.get("amr", [])
    methods = {str(item).lower() for item in amr} if isinstance(amr, list) else set()
    if methods & {"hwk", "hardware_key", "hardware-key"}:
        return AuthLevel.HARDWARE_KEY
    if methods & {"webauthn", "fido", "passkey"}:
        return AuthLevel.PASSKEY
    return AuthLevel.FEDERATED
