import { NavLink, Outlet } from 'react-router-dom';

const navItems = [
  { path: '/', label: '仪表盘', icon: '📊' },
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
  return (
    <div className="flex h-screen overflow-hidden">
      {/* 左侧导航 220px（深蓝标题栏 + 导航） */}
      <aside className="w-[220px] shrink-0 bg-primary-900 text-white flex flex-col">
        <div className="h-16 flex items-center gap-2 px-4 border-b border-white/10">
          <span className="text-xl">📈</span>
          <div>
            <div className="font-bold text-sm">AI 投资分析</div>
            <div className="text-xs opacity-70">v0.4.0</div>
          </div>
        </div>
        <nav className="flex-1 overflow-y-auto py-2">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                  isActive
                    ? 'bg-primary-700 text-white'
                    : 'text-white/80 hover:bg-primary-700/60 hover:text-white'
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
      <main className="flex-1 overflow-y-auto p-6">
        <Outlet />
      </main>
    </div>
  );
}
