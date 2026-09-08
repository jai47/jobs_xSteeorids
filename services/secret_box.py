"""Encrypt/decrypt user-stored LLM API keys (Fernet)."""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from config import settings

log = logging.getLogger(__name__)


def _fernet() -> Fernet:
    raw = (settings.llm_keys_encryption_key or "").strip()
    if raw:
        try:
            return Fernet(raw.encode() if isinstance(raw, str) else raw)
        except Exception:
            # Accept raw 32-byte secrets by urlsafe-base64 encoding them.
            digest = hashlib.sha256(raw.encode()).digest()
            return Fernet(base64.urlsafe_b64encode(digest))

    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"jobs-xsteeorids-llm-keys-v1",
        info=b"user-llm-key-encryption",
    ).derive(settings.dashboard_secret.encode())
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        log.warning("Failed to decrypt LLM key (wrong encryption secret?)")
        raise ValueError("Unable to decrypt stored API key") from exc


def key_hint(plaintext: str) -> str:
    cleaned = plaintext.strip()
    if len(cleaned) <= 4:
        return cleaned
    return cleaned[-4:]
