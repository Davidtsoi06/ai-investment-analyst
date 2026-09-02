import { NavLink, Outlet } from 'react-router-dom';
import { useEffect, useState } from 'react';

const navItems = [
  { path: '/', label: '主页', icon: '🏠' },
  { path: '/news', label: '资讯看板', icon: '📰' },
  { path: '/portfolio', label: '持仓总览', icon: '💼' },
  { path: '/recommendation', label: '推荐中心', icon: '🎯' },
  { path: '/tracking', label: '追踪管理', icon: '📡' },
  { path: '/watchlist', label: '自选股看板', icon: '⭐' },
  { path: '/reports', label: '盘后报告', icon: '📋' },
  { path: '/risk', label: '风险分析', icon: '🛡️' },
  { path: '/review', label: '投资复盘', icon: '🔄' },
  { path: '/chat', label: '智能问答', icon: '💬' },
  { path: '/settings', label: '系统设置', icon: '⚙️' },
];

export default function AppLayout() {
  // 真实版本：优先主进程 app.getVersion()（IPC），其次 preload 注入，浏览器/开发环境兜底 dev
  const [appVersion, setAppVersion] = useState('');
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const [backendError, setBackendError] = useState<string | null>(null);

  // 后端连接状态检测（Electron 环境经 window.backend；浏览器直连调试不提示）
  useEffect(() => {
    if (!window.backend) return;
    let alive = true;
    const check = async () => {
      try {
        const st = await window.backend?.status();
        if (alive) {
          setBackendOk(!!st && st.running === true);
          setBackendError(st?.error || null);
        }
      } catch {
        if (alive) setBackendOk(false);
      }
    };
    void check();
    const t = window.setInterval(check, 20000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);

  // 真实版本：主进程 app.getVersion()（打包后即 package.json 版本）；preload 注入兜底；浏览器开发 dev
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        if (window.updater?.getVersion) {
          const v = await window.updater.getVersion();
          if (alive && v?.version) { setAppVersion(v.version); return; }
        }
      } catch { /* 忽略 */ }
      if (alive) setAppVersion(window.appInfo?.versions?.app || 'dev');
    })();
    return () => { alive = false; };
  }, []);

  return (
    <div className="flex h-screen overflow-hidden">
      {/* 左侧导航 220px（深蓝标题栏 + 导航，激活态对齐理财软件） */}
      <aside className="w-[220px] shrink-0 bg-primary-900 text-white flex flex-col">
        <div className="h-16 flex items-center gap-2 px-4 border-b border-white/10">
          <span className="text-xl">📈</span>
          <div>
            <div className="font-bold text-sm">AI 投资分析</div>
            <div className="text-xs opacity-70">v{appVersion || '…'}</div>
          </div>
        </div>
        <nav className="flex-1 overflow-y-auto py-2">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-2.5 text-sm transition-all border-l-[3px] ${
                  isActive
                    ? 'bg-white/15 text-white border-primary-300 font-medium'
                    : 'border-transparent text-white/80 hover:bg-white/10 hover:text-white'
                }`
              }
            >
              <span>{item.icon}</span>
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="p-3 text-xs text-white/50 border-t border-white/10">本地运行 · 数据安全</div>
      </aside>
      {/* 内容区 */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {backendOk === false && (
          <div className="bg-warning/15 border-b border-warning/40 px-4 py-1.5 text-xs font-medium text-warning">
            <div className="flex items-center justify-center gap-2">
              <span>⚠</span>
              <span>后端服务未连接，部分功能不可用（正在自动重试）</span>
            </div>
            {backendError && (
              <div className="text-center text-warning/80 mt-0.5 truncate" title={backendError}>
                {backendError}
              </div>
            )}
          </div>
        )}
        <div className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
