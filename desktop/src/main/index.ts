import { app, BrowserWindow } from 'electron';
import { createWindow } from './window';
import { createTray } from './tray';
import { setupUpdater } from './updater';

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

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  // 常驻后台：关闭窗口不退出应用，保留系统托盘
  app.on('window-all-closed', () => {
    // 不调用 app.quit()：托盘驻留，符合全天候在线设计
  });
}
