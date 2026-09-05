import { app, BrowserWindow, ipcMain, shell } from 'electron';
import * as path from 'path';
import { createWindow } from './window';
import { createTray } from './tray';
import { backendManager } from './backend';
import { setupUpdater, registerUpdateIpc } from './updater';
import { log } from './logger';

// F: 统一用户数据目录为英文名（与后端一致），避免双目录困惑
app.setPath('userData', path.join(app.getPath('appData'), 'ai-investment-analyst'));
log('INFO', '主进程启动，userData=' + app.getPath('userData'));

// IPC：渲染进程经主进程代理访问后端（避免 CORS 与令牌暴露）
ipcMain.handle('backend:request', (_e, payload: { method: string; path: string; body?: unknown }) =>
  backendManager.request(payload.method, payload.path, payload.body)
);
// 打开外部链接（仅允许 http/https，经系统默认浏览器）
ipcMain.handle('app:openExternal', (_e, url: string) => {
  if (typeof url === 'string' && /^https?:\/\//.test(url)) {
    void shell.openExternal(url);
    return { ok: true };
  }
  return { ok: false };
});
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
    } else {
      // A: 窗口已关闭（驻留托盘）时，再次双击直接重建窗口
      log('INFO', 'second-instance：无窗口，重建主窗口');
      createWindow();
    }
  });

  app.whenReady().then(() => {
    createWindow();
    createTray();
    setupUpdater();
    registerUpdateIpc();
    void backendManager.start(); // 拉起后端（不阻塞窗口）

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  // V1.0.5：× 关闭窗口即完全退出（before-quit 会停止后端进程）；最小化保持后台
  app.on('window-all-closed', () => {
    app.quit();
  });

  app.on('before-quit', () => {
    // C: 标记退出中（窗口关闭逻辑据此放行），并停止后端进程
    (app as { isQuitting?: boolean }).isQuitting = true;
    void backendManager.stop();
    log('INFO', '应用退出中');
  });
}
