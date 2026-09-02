import { BrowserWindow } from 'electron';
import * as path from 'path';

export function createWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1000,
    minHeight: 700,
    title: 'AI 投资分析软件',
    icon: path.join(__dirname, '../../assets/icon.png'),
    backgroundColor: '#F5F7FA',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // V1.0.5：× 按钮 = 完全退出（关闭窗口后由 window-all-closed 触发应用退出）；
  // 最小化则保持后台运行，点击任务栏可恢复。
  // 加载前端构建产物（构建脚本将 frontend/dist 复制到 app-renderer/）
  win.loadFile(path.join(__dirname, '../../app-renderer/index.html'));
  return win;
}
