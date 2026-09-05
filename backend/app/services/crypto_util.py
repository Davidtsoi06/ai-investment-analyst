# -*- coding: utf-8 -*-
"""敏感配置加密：Fernet(AES-128-CBC+HMAC)，密钥文件 data/secret.key（自动生成，不入库）

V1.0.7：解密失败不再静默——记录最近一次错误原因，供 /api/settings/ai-status 展示，
避免"明明保存过 Key 却显示未配置"的黑盒问题。
"""

from cryptography.fernet import Fernet
from cryptography.fernet import InvalidToken

from ..config import settings
from .logger import get_app_logger

logger = get_app_logger()

_fernet: Fernet | None = None
_last_error: str = ''


def get_last_error() -> str:
    """最近一次密钥操作失败原因（空 = 正常）"""
    return _last_error


def _set_error(msg: str) -> None:
    global _last_error
    _last_error = msg
    logger.error('密钥操作失败: %s', msg)


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key_path = settings.data_dir / 'secret.key'
        try:
            key_path.parent.mkdir(parents=True, exist_ok=True)
            if key_path.exists():
                key = key_path.read_bytes()
            else:
                key = Fernet.generate_key()
                key_path.write_bytes(key)
                logger.info('已生成新密钥文件 %s（若之前保存过 Key，需重新填写）', key_path)
        except Exception as e:  # noqa: BLE001
            _set_error(f'密钥文件读写失败（{key_path}）: {str(e)[:120]}')
            raise
        _fernet = Fernet(key)
    return _fernet


def encrypt_text(plain: str) -> str:
    return _get_fernet().encrypt(plain.encode('utf-8')).decode('utf-8')


def decrypt_text(token: str) -> str:
    try:
        return _get_fernet().decrypt(token.encode('utf-8')).decode('utf-8')
    except InvalidToken:
        _set_error('密钥解密失败：密钥文件已更换或数据损坏，请重新填写 API Key')
        return ''
    except Exception as e:  # noqa: BLE001
        _set_error(f'密钥解密失败: {str(e)[:120]}')
        return ''
