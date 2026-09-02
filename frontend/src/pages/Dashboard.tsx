// S16 仪表盘首页：资产总览 / 市场速览 / 快捷信息（今日推荐 + 宏观信号 + 最近通知）
// 契约：GET /api/portfolio/overview · GET /api/summary/snapshot?market= · GET /api/recommend/today · GET /api/macro/overview · GET /api/notifications
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import Card from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import Loading from '../components/ui/Loading';
import EmptyState from '../components/ui/EmptyState';
import Stat from '../components/ui/Stat';
import {
  getMacroOverview,
  getMarketSnapshot,
  getNotifications,
  getPortfolioOverview,
  getTodayRecommendations,
  parseApiError,
} from '../services/api';
import type {
  HoldingItem,
  MarketIndex,
  MacroOverview,
  NetWorth,
  NotificationItem,
  RecommendItem,
} from '../services/api';
import { fmtMoney, fmtNum, fmtPct, toList, upDownCls } from '../lib/format';

/** 宏观信号（四色）：兼容 level='green|yellow|red|black' 与 signal='🟢|🟡|🔴|⚫' */
const SIGNAL_META: Record<string, { label: string; emoji: string; desc: string; cls: string }> = {
  green: { label: '环境友好', emoji: '🟢', desc: '宏观环境友好，可正常操作', cls: 'bg-success/10 border-success/60 text-success' },
  yellow: { label: '中性偏谨慎', emoji: '🟡', desc: '宏观环境偏谨慎，控制仓位', cls: 'bg-warning/15 border-warning/70 text-warning' },
  red: { label: '风险偏高', emoji: '🔴', desc: '暂停短线操作，注意风险', cls: 'bg-danger/10 border-danger/70 text-danger' },
  black: { label: '系统性风险', emoji: '⚫', desc: '暂停买入，规避系统性风险', cls: 'bg-neutral-900 border-neutral-900 text-white' },
};

function resolveMacroLevel(m: MacroOverview | null | undefined): keyof typeof SIGNAL_META {
  const lvl = String(m?.level ?? '').trim().toLowerCase();
  if (lvl === 'green' || lvl === 'yellow' || lvl === 'red' || lvl === 'black') return lvl;
  const sig = String(m?.signal ?? '');
  if (sig.includes('🟢') || sig.toLowerCase().includes('green')) return 'green';
  if (sig.includes('🟡') || sig.toLowerCase().includes('yellow')) return 'yellow';
  if (sig.includes('🔴') || sig.toLowerCase().includes('red')) return 'red';
  if (sig.includes('⚫') || sig.toLowerCase().includes('black')) return 'black';
  return 'green';
}

const NOTIFY_LEVEL_BADGE: Record<string, 'danger' | 'warning' | 'info' | 'default'> = {
  紧急: 'danger',
  预警: 'danger',
  关注: 'warning',
  警告: 'warning',
  提示: 'info',
};

function IndexCard({ idx }: { idx: MarketIndex }) {
  return (
    <div className="bg-bg-secondary rounded px-4 py-3">
      <div className="flex items-center justify-between">
        <span className="text-xs text-text-secondary">{idx.name || idx.symbol}</span>
        <span className="text-xs text-text-muted font-number">{idx.symbol}</span>
      </div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-xl font-number font-bold leading-none">{fmtNum(idx.price, 2)}</span>
        <span className={`text-xs font-number ${upDownCls(idx.change_pct)}`}>
          {idx.change != null && idx.change !== 0 ? (idx.change > 0 ? '+' : '') + idx.change.toFixed(2) : ''}
          {idx.change_pct != null && idx.change_pct !== 0 ? ' ' + fmtPct(idx.change_pct, 2) : ''}
        </span>
      </div>
    </div>
  );
}

export default function Dashboard() {
  // ---- 资产总览 ----
  const [netWorth, setNetWorth] = useState<NetWorth | null>(null);
  const [holdings, setHoldings] = useState<HoldingItem[]>([]);
  const [ovLoading, setOvLoading] = useState(false);
  const [ovError, setOvError] = useState('');

  // ---- 市场速览 ----
  const [aIndices, setAIndices] = useState<MarketIndex[]>([]);
  const [hkIndices, setHkIndices] = useState<MarketIndex[]>([]);
  const [marketLoading, setMarketLoading] = useState(false);
  const [marketError, setMarketError] = useState('');

  // ---- 快捷信息 ----
  const [recs, setRecs] = useState<RecommendItem[]>([]);
  const [recLoading, setRecLoading] = useState(false);
  const [recError, setRecError] = useState('');
  const [macro, setMacro] = useState<MacroOverview | null>(null);
  const [macroLoading, setMacroLoading] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [notifyLoading, setNotifyLoading] = useState(false);

  useEffect(() => {
    setOvLoading(true);
    getPortfolioOverview()
      .then((r) => {
        if (r.ok && r.data) {
          const d = r.data;
          setHoldings(toList<HoldingItem>(d.holdings));
          setNetWorth(d.snapshot?.net_worth ?? null);
        } else {
          setOvError('资产数据获取失败：' + parseApiError(r.error));
        }
      })
      .catch(() => setOvError('资产数据获取失败：后端不可用'))
      .finally(() => setOvLoading(false));

    setMarketLoading(true);
    Promise.all([getMarketSnapshot('A股'), getMarketSnapshot('港股')])
      .then(([a, h]) => {
        setAIndices(toList<MarketIndex>(a.ok ? a.data?.indices : null));
        setHkIndices(toList<MarketIndex>(h.ok ? h.data?.indices : null));
        if (!a.ok && !h.ok) {
          setMarketError('指数行情获取失败：' + parseApiError(a.error));
        } else if (!a.ok || !h.ok) {
          setMarketError('部分市场指数获取失败（另一市场正常展示）');
        }
      })
      .catch(() => setMarketError('指数行情获取失败：后端不可用'))
      .finally(() => setMarketLoading(false));

    setRecLoading(true);
    getTodayRecommendations()
      .then((r) => {
        if (r.ok && r.data) setRecs(toList<RecommendItem>((r.data as { items?: unknown }).items).slice(0, 3));
        else setRecError('推荐获取失败：' + parseApiError(r.error));
      })
      .catch(() => setRecError('推荐获取失败：后端不可用'))
      .finally(() => setRecLoading(false));

    setMacroLoading(true);
    getMacroOverview()
      .then((r) => {
        if (r.ok && r.data) setMacro(r.data as MacroOverview);
        else setMacro(null);
      })
      .catch(() => setMacro(null))
      .finally(() => setMacroLoading(false));

    setNotifyLoading(true);
    getNotifications(3)
      .then((r) => {
        if (r.ok) setNotifications(toList<NotificationItem>(r.data));
      })
      .catch(() => { /* 通知失败静默，不阻塞首页 */ })
      .finally(() => setNotifyLoading(false));
  }, []);

  const holdingsValue = useMemo(
    () =>
      holdings.reduce((s, h) => {
        const qty = typeof h.quantity === 'number' ? h.quantity : 0;
        const price = typeof h.current_price === 'number' ? h.current_price : 0;
        return s + qty * price;
      }, 0),
    [holdings],
  );

  // 市场速览三卡：上证指数 / 深证成指 / 恒生指数
  const marketIndices = useMemo(() => {
    const map = new Map<string, MarketIndex>();
    for (const i of [...aIndices, ...hkIndices]) map.set(i.symbol, i);
    const order = ['sh000001', 'sz399001', 'hkHSI'];
    const picked: MarketIndex[] = [];
    for (const sym of order) {
      const it = map.get(sym);
      if (it) picked.push(it);
    }
    return picked;
  }, [aIndices, hkIndices]);

  const signal = resolveMacroLevel(macro);
  const signalMeta = SIGNAL_META[signal];

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-primary-900">主页</h1>
        <p className="text-xs text-text-muted mt-1">资产总览 · 市场速览 · 今日推荐 · 宏观信号 · 通知中心</p>
      </div>
      {ovError && <p className="text-sm text-danger">{ovError}</p>}

      {/* 1. 资产总览 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">资产总览</h2>
          <span className="text-xs text-text-muted">与个人理财软件只读同步 · 每小时自动刷新</span>
        </div>
        {ovLoading && !netWorth ? (
          <Loading />
        ) : netWorth ? (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              <Stat label="总资产（元）" value={fmtMoney(netWorth.net_worth)} />
              <Stat label="现金（元）" value={fmtMoney(netWorth.total_cash)} />
              <Stat label="投资（元）" value={fmtMoney(netWorth.total_investments)} />
            </div>
            <div className="flex flex-wrap items-center gap-2 mt-3 text-xs text-text-muted">
              <span>持仓 {holdings.length} 只</span>
              <span className="text-border">|</span>
              <span className="font-number">持仓市值 {fmtMoney(holdingsValue)}</span>
              {netWorth.date && (
                <>
                  <span className="text-border">|</span>
                  <span>净值日期 {netWorth.date}</span>
                </>
              )}
              <Link to="/portfolio" className="ml-auto text-primary-500 hover:text-primary-700">查看持仓明细 →</Link>
            </div>
          </>
        ) : (
          <EmptyState
            icon="💼"
            title="暂无资产数据"
            description="尚未与个人理财软件同步持仓，或后端未启动。可在「持仓总览」页手动同步。"
            action={<Link to="/portfolio"><Button size="sm" variant="secondary">前往持仓总览</Button></Link>}
          />
        )}
      </Card>

      {/* 2. 市场速览 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">市场速览</h2>
          <span className="text-xs text-text-muted">A股 · 港股主要指数（免费源，约 15 分钟延迟）</span>
        </div>
        {marketError && <p className="text-sm text-danger mb-2">{marketError}</p>}
        {marketLoading && marketIndices.length === 0 ? (
          <Loading />
        ) : marketIndices.length === 0 ? (
          <EmptyState icon="📈" title="暂无指数行情" description="行情数据源暂不可用，可稍后刷新重试。" />
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            {marketIndices.map((i) => <IndexCard key={i.symbol} idx={i} />)}
          </div>
        )}
      </Card>

      {/* 3. 宏观信号横幅 */}
      {macro && (
        <div className={`rounded-lg border px-4 py-3 ${signalMeta.cls}`}>
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-2xl">{signalMeta.emoji}</span>
            <div>
              <div className="font-bold text-base">{signalMeta.label}</div>
              <div className="text-xs opacity-80">{signalMeta.desc}</div>
            </div>
            <div className="ml-auto text-xs opacity-80">
              {macroLoading
                ? '信号更新中...'
                : (macro as { updated_at?: string })?.updated_at
                  ? '更新于 ' + String((macro as { updated_at?: string }).updated_at).slice(5, 16)
                  : '宏观研判'}
            </div>
          </div>
        </div>
      )}

      {/* 4. 快捷信息：今日推荐 + 最近通知 */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        <Card className="lg:col-span-3">
          <div className="flex flex-wrap items-center gap-2 mb-3">
            <h2 className="font-bold text-sm">今日推荐</h2>
            <span className="text-xs text-text-muted">短线 · 长线 前 3 条</span>
            <Link to="/recommendation" className="ml-auto text-primary-500 hover:text-primary-700 text-xs">全部推荐 →</Link>
          </div>
          {recError && <p className="text-sm text-danger mb-2">{recError}</p>}
          {recLoading && recs.length === 0 ? (
            <Loading />
          ) : recs.length === 0 ? (
            <EmptyState icon="🎯" title="今日暂无推荐" description="每个交易日 09:15 自动生成，也可到「推荐中心」手动生成。" />
          ) : (
            <div className="divide-y divide-border">
              {recs.map((rec) => (
                <div key={rec.id} className="py-2.5 flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="text-sm font-medium">{rec.name || rec.symbol}</span>
                  <span className="text-xs text-text-muted font-number">{rec.symbol}</span>
                  <Badge variant={rec.market === '港股' ? 'info' : 'default'}>{rec.market || 'A股'}</Badge>
                  <Badge variant={rec.rec_type === '短线' ? 'warning' : 'default'}>{rec.rec_type || '—'}</Badge>
                  <span className="ml-auto text-xs text-text-secondary">
                    置信度 <span className="font-number">{rec.confidence != null ? rec.confidence + '%' : '—'}</span>
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card className="lg:col-span-2">
          <div className="flex flex-wrap items-center gap-2 mb-3">
            <h2 className="font-bold text-sm">最近通知</h2>
            <span className="text-xs text-text-muted">应用内 3 条</span>
          </div>
          {notifyLoading && notifications.length === 0 ? (
            <Loading />
          ) : notifications.length === 0 ? (
            <EmptyState icon="🔔" title="暂无通知" description="盘前资讯、异动提醒、盘后总结等通知会显示在这里。" className="py-6" />
          ) : (
            <div className="divide-y divide-border">
              {notifications.map((n) => (
                <div key={n.id} className="py-2">
                  <div className="flex items-center gap-2">
                    {n.level && <Badge variant={NOTIFY_LEVEL_BADGE[n.level] || 'default'}>{n.level}</Badge>}
                    <span className="text-sm font-medium truncate flex-1">{n.title}</span>
                    {n.sent_at && <span className="text-xs text-text-muted font-number shrink-0">{String(n.sent_at).slice(5, 16)}</span>}
                  </div>
                  {n.content && <p className="text-xs text-text-secondary mt-0.5 line-clamp-2">{n.content}</p>}
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
