"""Autenticador WebAuthn de software para pruebas automáticas.

Sustituye a la passkey o a la llave física en las pruebas de integración con
el proveedor de identidad. Sólo existe en `tests/`: nunca se usa en la
aplicación. Genera las mismas estructuras que `navigator.credentials.create`
y `navigator.credentials.get` (clientDataJSON, authenticatorData,
attestationObject y firma ES256) para que el servidor las verifique igual que
las de un dispositivo real.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import uuid
from dataclasses import dataclass, field

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

# AAGUID fijo del autenticador de software: un servidor que exige una lista de
# AAGUID de llaves físicas debe rechazarlo.
AAGUID_SOFTWARE = uuid.UUID("00000000-0000-4000-8000-0000fac70001")

FLAG_UP = 0x01
FLAG_UV = 0x04
FLAG_AT = 0x40


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def cbor(value) -> bytes:
    """Codificador CBOR mínimo (enteros, bytes, texto, listas y mapas)."""
    if isinstance(value, bool):
        return b"\xf5" if value else b"\xf4"
    if isinstance(value, int):
        return _cbor_head(0, value) if value >= 0 else _cbor_head(1, -1 - value)
    if isinstance(value, bytes):
        return _cbor_head(2, len(value)) + value
    if isinstance(value, str):
        data = value.encode()
        return _cbor_head(3, len(data)) + data
    if isinstance(value, list):
        return _cbor_head(4, len(value)) + b"".join(cbor(item) for item in value)
    if isinstance(value, dict):
        items = sorted(((cbor(k), cbor(v)) for k, v in value.items()), key=lambda kv: (len(kv[0]), kv[0]))
        return _cbor_head(5, len(items)) + b"".join(k + v for k, v in items)
    raise TypeError(f"Tipo no soportado en CBOR: {type(value)!r}")


def _cbor_head(major: int, length: int) -> bytes:
    if length < 24:
        return bytes([major << 5 | length])
    if length < 0x100:
        return bytes([major << 5 | 24, length])
    if length < 0x10000:
        return bytes([major << 5 | 25]) + struct.pack(">H", length)
    return bytes([major << 5 | 26]) + struct.pack(">I", length)


@dataclass
class Credencial:
    credential_id: bytes
    private_key: ec.EllipticCurvePrivateKey
    rp_id: str
    user_handle: bytes
    sign_count: int = 0


@dataclass
class AutenticadorSoftware:
    """Autenticador ES256 con verificación de usuario siempre satisfecha."""

    origin: str
    aaguid: uuid.UUID = AAGUID_SOFTWARE
    formato_atestacion: str = "none"  # "none" o "packed" (autoatestación)
    credenciales: list[Credencial] = field(default_factory=list)

    def crear(self, *, challenge: bytes, rp_id: str, user_handle: bytes) -> dict[str, str]:
        """Equivalente a navigator.credentials.create(); devuelve campos en base64url."""
        private_key = ec.generate_private_key(ec.SECP256R1())
        credential_id = os.urandom(32)
        client_data = self._client_data("webauthn.create", challenge)
        auth_data = (
            hashlib.sha256(rp_id.encode()).digest()
            + bytes([FLAG_UP | FLAG_UV | FLAG_AT])
            + struct.pack(">I", 0)
            + self.aaguid.bytes
            + struct.pack(">H", len(credential_id))
            + credential_id
            + cbor(_cose_es256(private_key.public_key()))
        )
        firmado = auth_data + hashlib.sha256(client_data).digest()
        if self.formato_atestacion == "packed":
            att_stmt: dict = {"alg": -7, "sig": private_key.sign(firmado, ec.ECDSA(hashes.SHA256()))}
        elif self.formato_atestacion == "packed-x5c":
            clave_att, cert_der = _certificado_atestacion(self.aaguid)
            att_stmt = {"alg": -7, "sig": clave_att.sign(firmado, ec.ECDSA(hashes.SHA256())), "x5c": [cert_der]}
        else:
            att_stmt = {}
        fmt = "packed" if self.formato_atestacion.startswith("packed") else self.formato_atestacion
        attestation = cbor({"fmt": fmt, "attStmt": att_stmt, "authData": auth_data})
        self.credenciales.append(Credencial(credential_id, private_key, rp_id, user_handle))
        return {
            "clientDataJSON": b64url(client_data),
            "attestationObject": b64url(attestation),
            "publicKeyCredentialId": b64url(credential_id),
        }

    def obtener(self, *, challenge: bytes, rp_id: str, permitidas: list[bytes] | None = None) -> dict[str, str]:
        """Equivalente a navigator.credentials.get(); usa la primera credencial válida."""
        candidatas = [
            c for c in self.credenciales
            if c.rp_id == rp_id and (not permitidas or c.credential_id in permitidas)
        ]
        if not candidatas:
            raise LookupError("El autenticador no tiene credenciales para este sitio")
        cred = candidatas[0]
        cred.sign_count += 1
        client_data = self._client_data("webauthn.get", challenge)
        auth_data = (
            hashlib.sha256(rp_id.encode()).digest()
            + bytes([FLAG_UP | FLAG_UV])
            + struct.pack(">I", cred.sign_count)
        )
        firma = cred.private_key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            "clientDataJSON": b64url(client_data),
            "authenticatorData": b64url(auth_data),
            "signature": b64url(firma),
            "credentialId": b64url(cred.credential_id),
            "userHandle": b64url(cred.user_handle),
        }

    def _client_data(self, tipo: str, challenge: bytes) -> bytes:
        return json.dumps(
            {"type": tipo, "challenge": b64url(challenge), "origin": self.origin, "crossOrigin": False},
            separators=(",", ":"),
        ).encode()


def _certificado_atestacion(aaguid: uuid.UUID) -> tuple[ec.EllipticCurvePrivateKey, bytes]:
    """Certificado de atestación con el formato de un fabricante, firmado por una CA
    de prueba que el servidor no conoce. Sirve para comprobar que el servidor valida
    la cadena de confianza y no sólo el AAGUID declarado."""
    from datetime import datetime, timedelta, timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.x509.oid import NameOID

    ahora = datetime.now(timezone.utc)
    clave_ca = ec.generate_private_key(ec.SECP256R1())
    nombre_ca = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CA de prueba no confiable")])
    clave = ec.generate_private_key(ec.SECP256R1())
    sujeto = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "MX"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Fabricante de prueba"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Authenticator Attestation"),
        x509.NameAttribute(NameOID.COMMON_NAME, "Llave de prueba"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(sujeto)
        .issuer_name(nombre_ca)
        .public_key(clave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - timedelta(days=1))
        .not_valid_after(ahora + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.UnrecognizedExtension(x509.ObjectIdentifier("1.3.6.1.4.1.45724.1.1.4"), b"\x04\x10" + aaguid.bytes),
            critical=False,
        )
        .sign(clave_ca, hashes.SHA256())
    )
    return clave, cert.public_bytes(serialization.Encoding.DER)


def _cose_es256(public_key: ec.EllipticCurvePublicKey) -> dict:
    numeros = public_key.public_numbers()
    return {1: 2, 3: -7, -1: 1, -2: numeros.x.to_bytes(32, "big"), -3: numeros.y.to_bytes(32, "big")}
