import { BrowserWindow, app, dialog } from 'electron';
import * as path from 'path';

let trayHintShown = false;

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

  // B: 关闭窗口 → 驻留托盘（应用退出时放行）；首次关闭提示
  win.on('close', (e) => {
    const quitting = (app as { isQuitting?: boolean }).isQuitting === true;
    if (quitting) return; // 真正退出，放行
    e.preventDefault();
    win.hide();
    if (!trayHintShown) {
      trayHintShown = true;
      dialog.showMessageBox(win, {
        type: 'info',
        title: 'AI 投资分析软件',
        message: '已最小化到系统托盘',
        detail: '软件在后台持续运行（行情监控/资讯推送）。需要完全退出时，请右键系统托盘图标选择「退出」。',
        buttons: ['知道了'],
      }).catch(() => {});
    }
  });

  // 加载前端构建产物（构建脚本将 frontend/dist 复制到 app-renderer/）
  win.loadFile(path.join(__dirname, '../../app-renderer/index.html'));
  return win;
}
