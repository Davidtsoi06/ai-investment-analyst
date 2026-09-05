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

// 打开外部链接（经主进程系统浏览器，仅 http/https）
contextBridge.exposeInMainWorld('app', {
  openExternal: (url: string) => ipcRenderer.invoke('app:openExternal', url),
});

// 后端访问代理：渲染进程 -> IPC -> 主进程 -> 后端 HTTP（令牌由主进程持有）
contextBridge.exposeInMainWorld('backend', {
  request: (method: string, path: string, body?: unknown) =>
    ipcRenderer.invoke('backend:request', { method, path, body }),
  status: () => ipcRenderer.invoke('backend:status'),
});

// 应用更新（对齐理财软件：检查/下载/安装 + 状态事件）
contextBridge.exposeInMainWorld('updater', {
  getVersion: () => ipcRenderer.invoke('update:getVersion'),
  check: () => ipcRenderer.invoke('update:check'),
  download: () => ipcRenderer.invoke('update:download'),
  install: () => ipcRenderer.invoke('update:install'),
  onStatus: (cb: (data: Record<string, unknown>) => void) => {
    const h = (_e: unknown, data: Record<string, unknown>) => cb(data);
    ipcRenderer.on('update:status', h);
    return () => ipcRenderer.removeListener('update:status', h);
  },
});
