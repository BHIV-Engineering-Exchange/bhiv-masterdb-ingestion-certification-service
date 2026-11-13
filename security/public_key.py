"""Loading of TANTRA RS256 public keys from supported configuration formats."""
import base64
import binascii
import re
from typing import Union

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


PublicKeyInput = Union[str, rsa.RSAPublicKey]


def load_rsa_public_key(value: PublicKeyInput) -> rsa.RSAPublicKey:
    """Load an RSA public key from PEM or a base64 DER SubjectPublicKeyInfo value."""
    if isinstance(value, rsa.RSAPublicKey):
        key = value
    elif not isinstance(value, str) or not value.strip():
        raise ValueError("RSA public key is empty.")
    else:
        configured = value.replace("\\n", "\n").strip()
        try:
            key = serialization.load_pem_public_key(configured.encode("utf-8"))
        except ValueError:
            encoded_der = re.sub(r"\s+", "", configured)
            try:
                der = base64.b64decode(encoded_der, validate=True)
                key = serialization.load_der_public_key(der)
            except (ValueError, binascii.Error) as exc:
                raise ValueError(
                    "RSA public key must be PEM or a base64 DER SubjectPublicKeyInfo value."
                ) from exc

    if not isinstance(key, rsa.RSAPublicKey):
        raise ValueError("Public key must be RSA for RS256 verification.")
    if key.key_size < 2048:
        raise ValueError("RSA public key must be at least 2048 bits.")
    return key
