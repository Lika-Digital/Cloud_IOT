"""
Password hashing using stdlib hashlib (PBKDF2-HMAC-SHA256).
No C-extension dependencies — works on 32-bit Python.
"""
import hashlib
import os
import binascii

ITERATIONS = 260_000


def hash_password(plain: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, ITERATIONS)
    return binascii.hexlify(salt).decode() + ":" + binascii.hexlify(dk).decode()


def verify_password(plain: str, stored_hash: str) -> bool:
    try:
        salt_hex, dk_hex = stored_hash.split(":", 1)
        salt = binascii.unhexlify(salt_hex)
        dk = binascii.unhexlify(dk_hex)
        new_dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, ITERATIONS)
        return new_dk == dk
    except Exception:
        return False
