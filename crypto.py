"""密码散列（PBKDF2）+ 用户密钥加密（Fernet 对称加密）。"""
import base64
import hashlib
import os

from cryptography.fernet import Fernet

import config


def hash_password(password: str, salt: bytes = None):
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120000)
    return base64.b64encode(salt).decode(), base64.b64encode(dk).decode()


def verify_password(password: str, salt_b64: str, hash_b64: str) -> bool:
    salt = base64.b64decode(salt_b64)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120000)
    return base64.b64encode(dk).decode() == hash_b64


def _fernet():
    config.ensure_dirs()
    if os.path.exists(config.SECRET_KEY_PATH):
        with open(config.SECRET_KEY_PATH, "rb") as f:
            key = f.read()
    else:
        key = Fernet.generate_key()
        with open(config.SECRET_KEY_PATH, "wb") as f:
            f.write(key)
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode()


def decrypt(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    return _fernet().decrypt(ciphertext.encode("utf-8")).decode()
