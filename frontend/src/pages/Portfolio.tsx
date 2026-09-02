// S16 持仓总览：持仓明细（含盈亏）/ 双数据来源（快照文件同步 ↔ 手动录入）/ 资产配置摘要
// 契约：GET /api/portfolio/overview · GET/PUT /api/portfolio/mode · POST /api/portfolio/sync
//       POST/DELETE /api/portfolio/holdings
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import Card from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import Loading from '../components/ui/Loading';
import EmptyState from '../components/ui/EmptyState';
import Stat from '../components/ui/Stat';
import {
  addPortfolioHolding,
  getPortfolioOverview,
  getPortfolioStatus,
  parseApiError,
  removePortfolioHolding,
  setPortfolioMode,
  syncPortfolio,
} from '../services/api';
import type { HoldingItem, NetWorth, PortfolioAccount, PortfolioOverview, PortfolioStatus } from '../services/api';
import { fmtMoney, fmtPct, fmtPrice, fmtTime, num, toList, upDownCls } from '../lib/format';

const inputCls = 'rounded border border-border px-2.5 py-2 text-sm w-full focus:outline-none focus:border-primary-500 bg-white';
const labelCls = 'text-xs text-text-secondary mb-1 block';

export default function Portfolio() {
  const [overview, setOverview] = useState<PortfolioOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const [status, setStatus] = useState<PortfolioStatus | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  // 手动录入表单
  const [form, setForm] = useState({ symbol: '', name: '', market: 'A股', quantity: '', cost_price: '' });
  const [adding, setAdding] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  const mode = (overview?.mode as string) || status?.mode || 'snapshot';

  const flash = (type: 'ok' | 'err', text: string) => {
    setMsg({ type, text });
    window.setTimeout(() => setMsg(null), 6000);
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    const r = await getPortfolioOverview();
    setLoading(false);
    if (r.ok && r.data) setOverview(r.data as PortfolioOverview);
    else setError('持仓数据获取失败：' + parseApiError(r.error));
  }, []);

  const loadStatus = useCallback(async () => {
    const r = await getPortfolioStatus();
    if (r.ok && r.data) setStatus(r.data as PortfolioStatus);
  }, []);

  useEffect(() => {
    load();
    loadStatus();
  }, [load, loadStatus]);

  const handleSync = async () => {
    setSyncing(true);
    setMsg(null);
    const r = await syncPortfolio();
    setSyncing(false);
    if (!r.ok) {
      flash('err', '同步失败：' + parseApiError(r.error));
      return;
    }
    const d = r.data as { ok?: boolean; reason?: string; holdings?: number; net_worth?: NetWorth | null; synced_at?: string };
    if (d?.ok === false) {
      flash('err', d.reason || '同步失败');
      return;
    }
    flash('ok', '同步完成：持仓 ' + (typeof d?.holdings === 'number' ? d.holdings : '—') + ' 只'
      + (d?.net_worth?.net_worth != null ? ' · 净值 ' + fmtMoney(d.net_worth.net_worth) : '')
      + (d?.synced_at ? ' · ' + String(d.synced_at).slice(0, 16) : ''));
    await Promise.all([load(), loadStatus()]);
  };

  const handleSwitchMode = async (m: 'manual' | 'snapshot') => {
    if (m === mode) return;
    const okGo = window.confirm(
      m === 'manual'
        ? '切换到「手动录入」后将清理此前从快照同步的持仓（可随时切回并重新同步）。继续？'
        : '切换到「快照文件」模式后，持仓来自理财软件导出的快照文件；已有手动录入保留（再次切回手动可恢复）。继续？',
    );
    if (!okGo) return;
    setSwitching(true);
    setMsg(null);
    const r = await setPortfolioMode(m);
    setSwitching(false);
    if (!r.ok || (r.data as { ok?: boolean })?.ok === false) {
      flash('err', '切换失败：' + (parseApiError(r.error) || ((r.data as { reason?: string })?.reason ?? '')));
      return;
    }
    flash('ok', m === 'manual' ? '已切换为手动录入模式' : '已切换为快照文件模式，可点击「同步持仓」导入');
    await Promise.all([load(), loadStatus()]);
  };

  const handleAdd = async () => {
    const symbol = form.symbol.trim();
    const qty = Number(form.quantity);
    const cost = Number(form.cost_price);
    if (!symbol) return flash('err', '请输入股票代码');
    if (!Number.isFinite(qty) || qty <= 0) return flash('err', '请输入大于 0 的数量');
    if (!Number.isFinite(cost) || cost < 0) return flash('err', '请输入有效的成本价');
    setAdding(true);
    setMsg(null);
    const r = await addPortfolioHolding({
      symbol,
      name: form.name.trim() || symbol,
      market: form.market,
      quantity: qty,
      cost_price: cost,
    });
    setAdding(false);
    const d = r.data as { ok?: boolean; reason?: string; action?: string };
    if (!r.ok || d?.ok === false) {
      flash('err', '添加失败：' + (parseApiError(r.error) || d?.reason || ''));
      return;
    }
    flash('ok', d?.action === 'updated' ? '已更新持仓（同代码覆盖）' : '已添加持仓');
    setForm({ symbol: '', name: '', market: 'A股', quantity: '', cost_price: '' });
    await Promise.all([load(), loadStatus()]);
  };

  const handleDelete = async (h: HoldingItem) => {
    if (!window.confirm('删除手动持仓「' + (h.name || h.symbol) + '」？')) return;
    setDeleting(String(h.symbol));
    const r = await removePortfolioHolding(String(h.symbol), String(h.market || 'A股'));
    setDeleting(null);
    if (!r.ok || (r.data as { ok?: boolean })?.ok === false) {
      flash('err', '删除失败：' + parseApiError(r.error));
      return;
    }
    flash('ok', '已删除');
    await Promise.all([load(), loadStatus()]);
  };

  const holdings = useMemo<HoldingItem[]>(() => toList<HoldingItem>(overview?.holdings), [overview]);
  const snapshot = overview?.snapshot;
  const accounts = useMemo<PortfolioAccount[]>(() => toList<PortfolioAccount>(snapshot?.accounts), [snapshot]);
  const netWorth = snapshot?.net_worth ?? null;

  const totalMarketValue = useMemo(
    () => holdings.reduce((s, h) => s + (num(h.quantity) ?? 0) * (num(h.current_price) ?? 0), 0),
    [holdings],
  );
  const totalCost = useMemo(
    () => holdings.reduce((s, h) => s + (num(h.quantity) ?? 0) * (num(h.cost_price) ?? 0), 0),
    [holdings],
  );
  const totalPnl = totalMarketValue - totalCost;
  const isManual = mode === 'manual';

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-primary-900">持仓总览</h1>
          <p className="text-xs text-text-muted mt-1">
            {isManual ? '手动录入模式：直接添加/编辑/删除持仓' : '快照文件模式：从个人理财软件导出的持仓快照同步（每小时自动）'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={load} disabled={loading}>
            {loading ? '刷新中...' : '刷新'}
          </Button>
          {!isManual && (
            <Button onClick={handleSync} disabled={syncing}>
              {syncing ? '同步中...' : '同步持仓'}
            </Button>
          )}
        </div>
      </div>
      {msg && <p className={'text-sm ' + (msg.type === 'ok' ? 'text-success' : 'text-danger')}>{msg.text}</p>}
      {error && <p className="text-sm text-danger">{error}</p>}

      {/* 数据来源 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-2">
          <h2 className="font-bold text-sm">持仓数据来源</h2>
          {status ? (
            isManual ? <Badge variant="warning">手动录入</Badge> : <Badge variant="info">快照文件</Badge>
          ) : (
            <Badge>检测中...</Badge>
          )}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          <button
            onClick={() => handleSwitchMode('snapshot')}
            disabled={switching}
            className={'rounded-lg border p-3 text-left text-sm transition ' + (!isManual ? 'border-primary-500 bg-primary-50' : 'border-border hover:border-primary-300')}
          >
            <div className="font-medium text-primary-900">☁️ 快照文件（理财软件同步）</div>
            <p className="text-xs text-text-secondary mt-1">读取「个人理财投资软件」导出的 portfolio_snapshot.json（v1.10.15+ 自动导出），含持仓/账户/交易/净值，每小时自动同步。</p>
            {!isManual && status && (
              <p className="text-xs text-text-muted mt-1">
                {status.snapshot_detected
                  ? '快照文件已检测到 · 更新于 ' + (status.snapshot_modified_at || '—')
                  : '尚未检测到快照文件，请先导出'}
              </p>
            )}
          </button>
          <button
            onClick={() => handleSwitchMode('manual')}
            disabled={switching}
            className={'rounded-lg border p-3 text-left text-sm transition ' + (isManual ? 'border-primary-500 bg-primary-50' : 'border-border hover:border-primary-300')}
          >
            <div className="font-medium text-primary-900">✏️ 手动录入</div>
            <p className="text-xs text-text-secondary mt-1">不使用理财软件，直接录入股票代码/数量/成本价自行管理持仓。录入后推荐、风险、复盘等均按此计算。</p>
          </button>
        </div>
        {!status?.snapshot_detected && !isManual && (
          <p className="text-xs text-warning mt-2">
            快照文件不存在：请在「个人理财投资软件」设置 → AI 配置 → 导出文件夹，指向{' '}
            <span className="font-mono">{status?.snapshot_dir || '本软件数据目录 data/portfolio'}</span>，并在理财软件中导出一次。
          </p>
        )}
      </Card>

      {/* 资产配置摘要（仅快照模式有账户/净值数据） */}
      {!isManual && (
        <Card>
          <div className="flex flex-wrap items-center gap-2 mb-3">
            <h2 className="font-bold text-sm">资产配置摘要</h2>
            <span className="text-xs text-text-muted">理财软件快照 · 账户现金与总净值</span>
          </div>
          {netWorth ? (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mb-3">
              <Stat label="总资产（元）" value={fmtMoney(netWorth.net_worth)} />
              <Stat label="现金（元）" value={fmtMoney(netWorth.total_cash)} />
              <Stat label="投资（元）" value={fmtMoney(netWorth.total_investments)} />
            </div>
          ) : loading ? (
            <Loading className="py-4" />
          ) : (
            <EmptyState
              icon="🏦"
              title="暂无净值快照"
              description="点击右上角「同步持仓」后，账户与净值摘要将显示在这里。"
              className="py-6"
            />
          )}
          {accounts.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-bg-secondary">
                    <th className="px-3 py-2 text-left font-medium text-text-secondary">账户</th>
                    <th className="px-3 py-2 text-left font-medium text-text-secondary">券商</th>
                    <th className="px-3 py-2 text-center font-medium text-text-secondary">币种</th>
                    <th className="px-3 py-2 text-right font-medium text-text-secondary">现金余额</th>
                  </tr>
                </thead>
                <tbody>
                  {accounts.map((a, i) => (
                    <tr key={a.name + i} className="border-t border-border hover:bg-primary-50">
                      <td className="px-3 py-2 font-medium">{a.name || '—'}</td>
                      <td className="px-3 py-2 text-text-secondary">{a.broker || '—'}</td>
                      <td className="px-3 py-2 text-center"><Badge variant="default">{a.currency || '—'}</Badge></td>
                      <td className="px-3 py-2 text-right font-number">{fmtMoney(a.cash_balance)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {/* 持仓明细 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">持仓明细</h2>
          <span className="text-xs text-text-muted">
            {holdings.length + ' 只'}
            {holdings.length > 0 && (
              <>
                <span className="mx-1.5 text-border">|</span>
                市值 <span className={'font-number ' + upDownCls(totalPnl)}>{fmtMoney(totalMarketValue)}</span>
                <span className="mx-1.5 text-border">|</span>
                浮动盈亏 <span className={'font-number ' + upDownCls(totalPnl)}>{fmtMoney(totalPnl)}</span>
              </>
            )}
          </span>
        </div>
        {loading && holdings.length === 0 ? (
          <Loading />
        ) : holdings.length === 0 ? (
          <EmptyState
            icon="💼"
            title="暂无持仓"
            description={
              isManual
                ? '点击下方「手动录入持仓」添加第一只股票。'
                : '点击右上角「同步持仓」从理财软件快照导入；若未导出，请在上方「数据来源」查看指引。'
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-bg-secondary">
                  <th className="px-3 py-2 text-left font-medium text-text-secondary">股票</th>
                  <th className="px-3 py-2 text-center font-medium text-text-secondary">市场</th>
                  <th className="px-3 py-2 text-right font-medium text-text-secondary">数量</th>
                  <th className="px-3 py-2 text-right font-medium text-text-secondary">成本价</th>
                  <th className="px-3 py-2 text-right font-medium text-text-secondary">现价</th>
                  <th className="px-3 py-2 text-right font-medium text-text-secondary">市值</th>
                  <th className="px-3 py-2 text-right font-medium text-text-secondary">盈亏</th>
                  <th className="px-3 py-2 text-right font-medium text-text-secondary">盈亏率</th>
                  {isManual && <th className="px-3 py-2 text-center font-medium text-text-secondary">操作</th>}
                </tr>
              </thead>
              <tbody>
                {holdings.map((h) => {
                  const qty = num(h.quantity) ?? 0;
                  const cost = num(h.cost_price) ?? 0;
                  const price = num(h.current_price) ?? 0;
                  const mv = qty * price;
                  const pnl = qty * (price - cost);
                  const pnlPct = cost > 0 ? (price / cost - 1) * 100 : null;
                  const market = h.market || 'A股';
                  return (
                    <tr key={h.symbol + (h.market || '')} className="border-t border-border hover:bg-primary-50">
                      <td className="px-3 py-2">
                        <div className="font-medium">{h.name || h.symbol}</div>
                        <div className="text-xs text-text-muted font-number">{h.symbol}</div>
                      </td>
                      <td className="px-3 py-2 text-center"><Badge variant={market === '港股' ? 'info' : 'default'}>{market}</Badge></td>
                      <td className="px-3 py-2 text-right font-number">{qty}</td>
                      <td className="px-3 py-2 text-right font-number">{fmtPrice(cost, market)}</td>
                      <td className="px-3 py-2 text-right font-number">{price > 0 ? fmtPrice(price, market) : '—'}</td>
                      <td className="px-3 py-2 text-right font-number">{price > 0 ? fmtMoney(mv) : '—'}</td>
                      <td className={'px-3 py-2 text-right font-number ' + upDownCls(pnl)}>{price > 0 ? fmtMoney(pnl) : '—'}</td>
                      <td className={'px-3 py-2 text-right font-number ' + upDownCls(pnlPct)}>{price > 0 ? fmtPct(pnlPct) : '—'}</td>
                      {isManual && (
                        <td className="px-3 py-2 text-center">
                          <button
                            disabled={deleting === String(h.symbol)}
                            onClick={() => handleDelete(h)}
                            className="rounded px-2 py-1 text-xs font-medium bg-danger/10 text-danger hover:bg-danger/20 disabled:opacity-50"
                          >
                            {deleting === String(h.symbol) ? '删除中...' : '删除'}
                          </button>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {!isManual && holdings.length > 0 && (
              <p className="text-xs text-text-muted mt-2">
                现价为本地行情估值，可能与理财软件记录存在差异；最近同步时间 {holdings[0]?.sync_at ? fmtTime(holdings[0].sync_at) : '—'}
              </p>
            )}
          </div>
        )}
      </Card>

      {/* 手动录入（manual 模式可用；快照模式提示去切换） */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">手动录入持仓</h2>
          {isManual ? <Badge variant="success">当前模式</Badge> : <Badge variant="default">需切换到手动模式</Badge>}
        </div>
        {isManual ? (
          <>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
              <div>
                <label className={labelCls}>代码 *</label>
                <input className={inputCls} placeholder="如 600519 / 00700" value={form.symbol}
                  onChange={(e) => setForm({ ...form, symbol: e.target.value })} />
              </div>
              <div>
                <label className={labelCls}>名称（选填）</label>
                <input className={inputCls} placeholder="留空用代码" value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div>
                <label className={labelCls}>市场</label>
                <select className={inputCls} value={form.market}
                  onChange={(e) => setForm({ ...form, market: e.target.value })}>
                  <option value="A股">A股</option>
                  <option value="港股">港股</option>
                </select>
              </div>
              <div>
                <label className={labelCls}>数量（股）*</label>
                <input className={inputCls} type="number" min="0" placeholder="100" value={form.quantity}
                  onChange={(e) => setForm({ ...form, quantity: e.target.value })} />
              </div>
              <div>
                <label className={labelCls}>成本价（元）*</label>
                <input className={inputCls} type="number" min="0" step="0.001" placeholder="0.00" value={form.cost_price}
                  onChange={(e) => setForm({ ...form, cost_price: e.target.value })} />
              </div>
            </div>
            <div className="mt-3 flex items-center gap-3">
              <Button onClick={handleAdd} disabled={adding || switching}>
                {adding ? '添加中...' : '添加 / 更新持仓'}
              </Button>
              <span className="text-xs text-text-muted">同代码+市场再次提交将覆盖数量与成本价；现价由本地行情自动获取</span>
            </div>
          </>
        ) : (
          <p className="text-xs text-text-secondary leading-5">
            当前为「快照文件」模式，持仓由理财软件自动同步。如需手动录入，请先在上方「数据来源」切换到{' '}
            <button className="text-primary-600 underline" onClick={() => handleSwitchMode('manual')} disabled={switching}>
              手动录入
            </button>{' '}
            （也可在{' '}
            <Link to="/settings" className="text-primary-600 underline">系统设置 → 持仓数据来源</Link> 中切换）。
          </p>
        )}
      </Card>
    </div>
  );
}
