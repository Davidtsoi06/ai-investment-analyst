import os
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

if getattr(sys, 'frozen', False):
    # PyInstaller 打包环境：数据目录 = %APPDATA%/ai-investment-analyst
    # （可用环境变量 AI_INVEST_DATA_DIR 覆盖）
    _default_data = Path(os.environ.get('APPDATA', str(Path.home()))) / 'ai-investment-analyst'
    PROJECT_ROOT = Path(os.environ.get('AI_INVEST_DATA_DIR', str(_default_data)))
else:
    # 开发环境：backend/app/config.py -> 项目根目录
    PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """应用配置：支持 .env 覆盖（项目根目录下）"""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / '.env',
        env_file_encoding='utf-8',
        extra='ignore',
    )

    app_name: str = 'AI 投资分析软件'
    version: str = '0.5.0'
    host: str = '127.0.0.1'
    port: int = 8756

    data_dir: Path = PROJECT_ROOT / 'data'
    db_path: Path = PROJECT_ROOT / 'data' / 'ai_invest.db'
    log_dir: Path = PROJECT_ROOT / 'data' / 'logs'

    # 启动令牌：由 Electron 主进程生成并通过环境变量 BACKEND_TOKEN 注入；
    # 为空时（手动开发模式）不校验。
    backend_token: str = ''

    # DeepSeek（S7 由引导配置写入 .env，此处提供默认空值）
    deepseek_api_key: str = ''
    deepseek_base_url: str = 'https://api.deepseek.com'
    model_chat: str = 'deepseek-chat'
    model_reasoner: str = 'deepseek-reasoner'


settings = Settings()
