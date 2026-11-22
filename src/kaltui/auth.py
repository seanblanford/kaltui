"""Optional in-memory request signing. No key creation, uploads, or credential cache."""

from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

from .errors import KaltuiError


@dataclass(frozen=True)
class Credentials:
    key_id: str = field(repr=False)
    private_key: rsa.RSAPrivateKey | ed25519.Ed25519PrivateKey = field(repr=False)

    @classmethod
    def from_environment(cls) -> Credentials | None:
        key_id = os.environ.get("KALSHI_API_KEY_ID", "").strip()
        path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "").strip()
        if not key_id and not path:
            return None
        if not key_id or not path:
            raise KaltuiError("Set both KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH, or neither.")
        try:
            key = serialization.load_pem_private_key(
                Path(path).expanduser().read_bytes(), password=None
            )
        except PermissionError:
            raise KaltuiError(
                "OS permission denied reading the private key. Fix permissions before continuing."
            ) from None
        except (OSError, ValueError, TypeError):
            raise KaltuiError(
                "Cannot load the private key; provide an unencrypted RSA or Ed25519 PEM file."
            ) from None
        if not isinstance(key, (rsa.RSAPrivateKey, ed25519.Ed25519PrivateKey)):
            raise KaltuiError("The private key must use RSA or Ed25519.")
        if any(ord(char) < 33 or ord(char) > 126 for char in key_id):
            raise KaltuiError("The API key ID must contain printable ASCII without spaces.")
        return cls(key_id, key)

    def headers(self, path: str) -> dict[str, str]:
        if path not in (
            "/trade-api/v2/portfolio/balance",
            "/trade-api/v2/portfolio/positions",
            "/trade-api/v2/portfolio/orders",
        ):
            raise KaltuiError("Signing is restricted to the three read-only portfolio endpoints.")
        timestamp = str(time.time_ns() // 1_000_000)
        message = f"{timestamp}GET{path}".encode("ascii")
        if isinstance(self.private_key, ed25519.Ed25519PrivateKey):
            signature = self.private_key.sign(message)
        else:
            signature = self.private_key.sign(
                message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH
                ),
                hashes.SHA256(),
            )
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("ascii"),
        }
