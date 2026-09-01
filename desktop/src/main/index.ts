import { app, BrowserWindow, ipcMain } from 'electron';
import * as path from 'path';
import { createWindow } from './window';
import { createTray } from './tray';
import { setupUpdater } from './updater';
import { backendManager } from './backend';
import { log } from './logger';

// F: 统一用户数据目录为英文名（与后端一致），避免双目录困惑
app.setPath('userData', path.join(app.getPath('appData'), 'ai-investment-analyst'));
log('INFO', '主进程启动，userData=' + app.getPath('userData'));

// IPC：渲染进程经主进程代理访问后端（避免 CORS 与令牌暴露）
ipcMain.handle('backend:request', (_e, payload: { method: string; path: string; body?: unknown }) =>
  backendManager.request(payload.method, payload.path, payload.body)
);
ipcMain.handle('backend:status', () => backendManager.getStatus());

// 单实例锁：避免重复启动
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    const win = BrowserWindow.getAllWindows()[0];
    if (win) {
      if (win.isMinimized()) win.restore();
      win.show();
      win.focus();
    }
  });

  app.whenReady().then(() => {
    createWindow();
    createTray();
    setupUpdater();
    void backendManager.start(); // 拉起后端（不阻塞窗口）

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  // 常驻后台：关闭窗口不退出应用，保留系统托盘
  app.on('window-all-closed', () => {
    // 不调用 app.quit()：托盘驻留，符合全天候在线设计
  });

  app.on('before-quit', () => {
    void backendManager.stop();
  });
}
