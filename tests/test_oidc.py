import time
from datetime import datetime, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWK
from jwt.algorithms import RSAAlgorithm

from app.security.models import AuthLevel
from app.security.oidc import OIDCConfigurationError, OIDCVerificationError, OIDCVerifier


ISSUER = "https://identity.example.test/"
AUDIENCE = "https://api.example.test"


class StaticJWKClient:
    def __init__(self, key):
        self.key = key

    def get_signing_key_from_jwt(self, _token):
        return self.key


@pytest.fixture(scope="module")
def signing_material():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk.update({"kid": "synthetic-test-key", "alg": "RS256", "use": "sig"})
    return private_key, PyJWK.from_dict(public_jwk)


def token(private_key, **overrides):
    now = int(time.time())
    claims = {
        "sub": "idp|synthetic-user",
        "sid": "synthetic-provider-session",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "auth_time": now - 10,
        "exp": now + 300,
        "amr": ["webauthn"],
    }
    claims.update(overrides)
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": "synthetic-test-key"},
    )


def verifier(public_jwk, **kwargs):
    instance = OIDCVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_url="https://identity.example.test/.well-known/jwks.json",
        **kwargs,
    )
    instance.jwks_client = StaticJWKClient(public_jwk)
    return instance


def test_valid_signed_token_produces_minimal_principal(signing_material):
    private_key, public_jwk = signing_material

    principal = verifier(public_jwk).verify(token(private_key))

    assert principal.subject == "idp|synthetic-user"
    assert principal.provider_session_id == "synthetic-provider-session"
    assert principal.auth_level is AuthLevel.PASSKEY
    assert principal.authenticated_at.tzinfo == timezone.utc


def test_wrong_audience_is_rejected(signing_material):
    private_key, public_jwk = signing_material

    with pytest.raises(OIDCVerificationError):
        verifier(public_jwk).verify(token(private_key, aud="https://another-api.example.test"))


def test_missing_session_claim_is_rejected(signing_material):
    private_key, public_jwk = signing_material
    now = int(time.time())
    invalid = jwt.encode(
        {
            "sub": "idp|synthetic-user",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "auth_time": now,
            "exp": now + 300,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "synthetic-test-key"},
    )

    with pytest.raises(OIDCVerificationError):
        verifier(public_jwk).verify(invalid)


def test_authentication_time_after_token_issue_is_rejected(signing_material):
    private_key, public_jwk = signing_material
    now = int(time.time())

    with pytest.raises(OIDCVerificationError):
        verifier(public_jwk).verify(token(private_key, iat=now, auth_time=now + 1))


def test_explicit_hardware_claim_is_required_to_raise_assurance(signing_material):
    private_key, public_jwk = signing_material
    claim = "https://api.example.test/auth_level"

    principal = verifier(public_jwk, auth_level_claim=claim).verify(
        token(private_key, **{claim: "HARDWARE_KEY", "amr": ["webauthn"]})
    )

    assert principal.auth_level is AuthLevel.HARDWARE_KEY


@pytest.mark.parametrize(
    ("issuer", "jwks_url"),
    [
        ("http://identity.example.test/", "https://identity.example.test/jwks.json"),
        ("https://identity.example.test/", "file:///tmp/jwks.json"),
        ("https://user:password@identity.example.test/", "https://identity.example.test/jwks.json"),
    ],
)
def test_oidc_metadata_requires_https_without_embedded_credentials(issuer, jwks_url):
    with pytest.raises(OIDCConfigurationError):
        OIDCVerifier(issuer=issuer, audience=AUDIENCE, jwks_url=jwks_url)
