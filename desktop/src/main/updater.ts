import { app, BrowserWindow, ipcMain } from 'electron';
import { autoUpdater, UpdateInfo } from 'electron-updater';
import { log } from './logger';

// 应用内自动更新（对齐个人理财投资软件）：启动自动检查 + 设置页手动检查/下载/安装

function broadcast(data: Record<string, unknown>): void {
  for (const w of BrowserWindow.getAllWindows()) {
    w.webContents.send('update:status', data);
  }
}

export function setupUpdater(): void {
  if (!app.isPackaged) return; // 开发模式不启用
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on('checking-for-update', () => {
    log('INFO', '[update] 正在检查更新');
    broadcast({ event: 'checking-for-update' });
  });
  autoUpdater.on('update-available', (info: UpdateInfo) => {
    log('INFO', `[update] 发现新版本 ${info.version}`);
    broadcast({ event: 'update-available', version: info.version });
  });
  autoUpdater.on('update-not-available', () => {
    log('INFO', '[update] 已是最新版本');
    broadcast({ event: 'update-not-available' });
  });
  autoUpdater.on('download-progress', (p) => {
    broadcast({ event: 'download-progress', percent: Math.round(p.percent) });
  });
  autoUpdater.on('update-downloaded', (info: UpdateInfo) => {
    log('INFO', `[update] 新版本 ${info.version} 下载完成`);
    broadcast({ event: 'update-downloaded', version: info.version });
  });
  autoUpdater.on('error', (err) => {
    log('ERROR', `[update] 更新错误: ${err.message}`);
    broadcast({ event: 'update-error', message: err.message });
  });

  // 启动 10 秒后自动检查一次（不打扰首次使用）
  setTimeout(() => {
    autoUpdater.checkForUpdates().catch(() => { /* 检查失败静默，日志已有 */ });
  }, 10_000);
}

// IPC：检查/下载/安装/版本信息
export function registerUpdateIpc(): void {
  ipcMain.handle('update:getVersion', () => ({
    version: app.getVersion(),
    devMode: !app.isPackaged,
  }));

  ipcMain.handle('update:check', async () => {
    if (!app.isPackaged) return { devMode: true, updateAvailable: false, message: '开发模式：更新功能仅在安装版生效' };
    try {
      const result = await autoUpdater.checkForUpdates();
      if (result && result.updateInfo.version !== app.getVersion()) {
        return { updateAvailable: true, currentVersion: app.getVersion(), latestVersion: result.updateInfo.version, releaseNotes: result.updateInfo.releaseNotes };
      }
      return { updateAvailable: false, currentVersion: app.getVersion(), message: '已是最新版本' };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return { updateAvailable: false, error: msg };
    }
  });

  ipcMain.handle('update:download', async () => {
    if (!app.isPackaged) return { devMode: true };
    try {
      await autoUpdater.downloadUpdate();
      return { success: true };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return { success: false, error: msg };
    }
  });

  ipcMain.handle('update:install', () => {
    autoUpdater.quitAndInstall(false, true);
    return { success: true };
  });
}
