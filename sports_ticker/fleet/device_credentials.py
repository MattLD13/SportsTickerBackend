"""Validate device credentials without exposing stored hashes in fleet projections."""
from __future__ import annotations
import hashlib
import re


def device_token_hash(token: str) -> str:
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{64}", token):
        raise ValueError("device token must contain sixty-four lowercase hexadecimal characters")
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def validate_device_hash(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("token_sha256 must contain sixty-four lowercase hexadecimal characters")
    return value
