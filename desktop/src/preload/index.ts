import { contextBridge } from 'electron';

// 向渲染进程安全暴露最小信息（S1 骨架，后续按需扩展）
contextBridge.exposeInMainWorld('appInfo', {
  versions: {
    app: process.env.npm_package_version || '',
    electron: process.versions.electron || '',
    chrome: process.versions.chrome || '',
    node: process.versions.node || '',
  },
});
