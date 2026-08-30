# -*- coding: utf-8 -*-
"""敏感配置加密：Fernet(AES-128-CBC+HMAC)，密钥文件 data/secret.key（自动生成，不入库）"""

from cryptography.fernet import Fernet

from ..config import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key_path = settings.data_dir / 'secret.key'
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if key_path.exists():
            key = key_path.read_bytes()
        else:
            key = Fernet.generate_key()
            key_path.write_bytes(key)
        _fernet = Fernet(key)
    return _fernet


def encrypt_text(plain: str) -> str:
    return _get_fernet().encrypt(plain.encode('utf-8')).decode('utf-8')


def decrypt_text(token: str) -> str:
    try:
        return _get_fernet().decrypt(token.encode('utf-8')).decode('utf-8')
    except Exception:  # noqa: BLE001
        return ''
