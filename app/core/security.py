from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from jose import jwt
from cryptography.fernet import Fernet
import base64

def _fernet_from_secret(secret: str) -> Fernet:
    # derive 32-byte key from secret (urlsafe base64). Pad/truncate deterministically.
    raw = secret.encode("utf-8")
    key = base64.urlsafe_b64encode((raw + b"0" * 32)[:32])
    return Fernet(key)

def create_access_token(data: dict[str, Any], secret: str, algorithm: str, minutes: int) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, secret, algorithm=algorithm)

def create_refresh_token(data: dict[str, Any], secret: str, algorithm: str, days: int) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=days)
    to_encode.update({"exp": expire, "typ": "refresh"})
    return jwt.encode(to_encode, secret, algorithm=algorithm)

def decode_token(token: str, secret: str, algorithms: list[str]) -> dict[str, Any]:
    return jwt.decode(token, secret, algorithms=algorithms)

def encrypt_oauth_token(token_json: str, secret: str) -> str:
    f = _fernet_from_secret(secret)
    return f.encrypt(token_json.encode("utf-8")).decode("utf-8")

def decrypt_oauth_token(token_cipher: str, secret: str) -> str:
    f = _fernet_from_secret(secret)
    return f.decrypt(token_cipher.encode("utf-8")).decode("utf-8")
