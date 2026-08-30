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

  // S1：加载内置最小页面；S2 起改为加载 frontend 构建产物
  win.loadFile(path.join(__dirname, '../../renderer/index.html'));
  return win;
}
