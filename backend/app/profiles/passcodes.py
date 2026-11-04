"""Names and passcodes. Standard library only; a passcode is never stored, only its scrypt hash."""
import hashlib
import hmac
import secrets
import unicodedata

_N, _R, _P = 2 ** 14, 8, 1
_BURN_SALT = bytes(16)


def normalize_name(name: str) -> str:
    cleaned = " ".join(unicodedata.normalize("NFKC", name).split())
    if not 2 <= len(cleaned) <= 40:
        raise ValueError("name must be 2 to 40 characters")
    return cleaned


def name_key(name: str) -> str:
    return normalize_name(name).casefold()


def validate_passcode(passcode: str) -> None:
    if not 6 <= len(passcode) <= 200:
        raise ValueError("passcode must be 6 to 200 characters")


def _scrypt(passcode: str, salt: bytes) -> bytes:
    return hashlib.scrypt(passcode.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)


def hash_passcode(passcode: str) -> tuple[str, str]:
    salt = secrets.token_bytes(16)
    return salt.hex(), _scrypt(passcode, salt).hex()


def verify_passcode(passcode: str, salt_hex: str, hash_hex: str) -> bool:
    return hmac.compare_digest(_scrypt(passcode, bytes.fromhex(salt_hex)), bytes.fromhex(hash_hex))


def burn_hash(passcode: str) -> None:
    """One scrypt computation, so an unknown name costs the same as a wrong passcode."""
    _scrypt(passcode, _BURN_SALT)
