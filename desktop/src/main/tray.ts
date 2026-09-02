import { app, BrowserWindow, Menu, Tray, nativeImage } from 'electron';
import { createWindow } from './window';
import * as path from 'path';

let tray: Tray | null = null;

export function createTray(): Tray {
  const icon = nativeImage.createFromPath(path.join(__dirname, '../../assets/icon.png'));
  tray = new Tray(icon.resize({ width: 16, height: 16 }));
  tray.setToolTip('AI 投资分析软件');

  const menu = Menu.buildFromTemplate([
    {
      label: '显示主窗口',
      click: () => {
        const w = BrowserWindow.getAllWindows()[0];
        if (w) { w.show(); w.focus(); }
        else { createWindow(); }
      },
    },
    { type: 'separator' },
    {
      label: '退出',
      click: () => { app.quit(); },
    },
  ]);
  tray.setContextMenu(menu);

  tray.on('double-click', () => {
    const w = BrowserWindow.getAllWindows()[0];
    if (w) { w.show(); w.focus(); }
  });
  return tray;
}
