import { app } from 'electron';
import { autoUpdater } from 'electron-updater';

// S1 骨架：仅初始化，不启用自动检查。
// 待 S4/S5 接入 GitHub Releases 发布源与升级提示 UI 后启用。
export function setupUpdater(): void {
  if (!app.isPackaged) return; // 开发模式不启用
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = true;
}
