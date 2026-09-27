from __future__ import annotations

from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError

_password_hash = PasswordHash.recommended()
_dummy_hash = _password_hash.hash("AWAS timing equalisation value - never a real password")


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, encoded_hash: str | None) -> bool:
    candidate_hash = encoded_hash or _dummy_hash
    try:
        return _password_hash.verify(password, candidate_hash)
    except (PwdlibError, TypeError, ValueError):
        return False
