import { contextBridge, ipcRenderer } from 'electron';

// 向渲染进程安全暴露最小信息
contextBridge.exposeInMainWorld('appInfo', {
  versions: {
    app: process.env.npm_package_version || '',
    electron: process.versions.electron || '',
    chrome: process.versions.chrome || '',
    node: process.versions.node || '',
  },
});

// 后端访问代理：渲染进程 -> IPC -> 主进程 -> 后端 HTTP（令牌由主进程持有）
contextBridge.exposeInMainWorld('backend', {
  request: (method: string, path: string, body?: unknown) =>
    ipcRenderer.invoke('backend:request', { method, path, body }),
  status: () => ipcRenderer.invoke('backend:status'),
});
