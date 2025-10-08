from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from jose import jwt
from cryptography.fernet import Fernet
import base64
import hashlib

# A salt should be unique and stored securely. For this example, we'll use a
# hardcoded salt. In a production environment, consider a better salt management strategy.
PBKDF2_SALT = b'\xdaI\x99\x0fX\x85\x9b\x93\xeb\x1a\x0e\x1f\r\x1a\x1b\x1d' # Example 16-byte salt

def _fernet_from_secret(secret: str) -> Fernet:
    """
    Derive a 32-byte key from the secret using PBKDF2 for use with Fernet.
    """
    kdf = hashlib.pbkdf2_hmac(
        'sha256',
        secret.encode('utf-8'),
        PBKDF2_SALT,
        100000, # Recommended number of iterations
        dklen=32  # Fernet keys must be 32 bytes
    )
    key = base64.urlsafe_b64encode(kdf)
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
