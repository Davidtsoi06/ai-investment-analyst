from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """应用配置：支持 .env 覆盖（项目根目录下）"""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / '.env',
        env_file_encoding='utf-8',
        extra='ignore',
    )

    app_name: str = 'AI 投资分析软件'
    version: str = '0.1.2'
    host: str = '127.0.0.1'
    port: int = 8756

    data_dir: Path = PROJECT_ROOT / 'data'
    db_path: Path = PROJECT_ROOT / 'data' / 'ai_invest.db'
    log_dir: Path = PROJECT_ROOT / 'data' / 'logs'

    # DeepSeek（S7 由引导配置写入 .env，此处提供默认空值）
    deepseek_api_key: str = ''
    deepseek_base_url: str = 'https://api.deepseek.com'
    model_chat: str = 'deepseek-chat'
    model_reasoner: str = 'deepseek-reasoner'


settings = Settings()
