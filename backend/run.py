import uvicorn
from app.config import settings
import app.main  # noqa: F401  显式导入，确保 PyInstaller 收集 app 包

if __name__ == '__main__':
    uvicorn.run('app.main:app', host=settings.host, port=settings.port, reload=False)
