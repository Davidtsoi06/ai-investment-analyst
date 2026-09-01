// S16 持仓总览：持仓明细（含盈亏）/ 理财软件同步 / 资产配置摘要 / 手动录入（占位）
// 契约：GET /api/portfolio/overview · GET /api/portfolio/status · POST /api/portfolio/sync
import { useCallback, useEffect, useMemo, useState } from 'react';
import Card from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import Loading from '../components/ui/Loading';
import EmptyState from '../components/ui/EmptyState';
import Stat from '../components/ui/Stat';
import {
  getPortfolioOverview,
  getPortfolioStatus,
  parseApiError,
  syncPortfolio,
} from '../services/api';
import type { HoldingItem, NetWorth, PortfolioAccount, PortfolioOverview, PortfolioStatus } from '../services/api';
import { fmtMoney, fmtPct, fmtPrice, fmtTime, num, toList, upDownCls } from '../lib/format';

function sourceVariant(source: string | null | undefined): 'info' | 'default' {
  return source === 'portfolio_app' ? 'info' : 'default';
}

function sourceLabel(source: string | null | undefined): string {
  return source === 'portfolio_app' ? '理财软件' : '手动';
}

export default function Portfolio() {
  const [overview, setOverview] = useState<PortfolioOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const [status, setStatus] = useState<PortfolioStatus | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

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
      setMsg({ type: 'err', text: '同步失败：' + parseApiError(r.error) });
      return;
    }
    const d = r.data as { ok?: boolean; reason?: string; holdings?: number; net_worth?: NetWorth | null; synced_at?: string };
    if (d?.ok === false) {
      setMsg({ type: 'err', text: d.reason || '同步失败' });
      return;
    }
    setMsg({
      type: 'ok',
      text: '同步完成：持仓 ' + (typeof d?.holdings === 'number' ? d.holdings : '—') + ' 只'
        + (d?.net_worth?.net_worth != null ? ' · 净值 ' + fmtMoney(d.net_worth.net_worth) : '')
        + (d?.synced_at ? ' · ' + String(d.synced_at).slice(0, 16) : ''),
    });
    await Promise.all([load(), loadStatus()]);
    window.setTimeout(() => setMsg(null), 6000);
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

  const inputCls = 'h-10 rounded border border-border px-3 text-sm bg-bg-secondary/60 text-text-muted cursor-not-allowed';

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-primary-900">持仓总览</h1>
          <p className="text-xs text-text-muted mt-1">与个人理财软件 finance.db 只读对接 · 每小时自动同步 · 手动录入将在后续版本开放</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={load} disabled={loading}>
            {loading ? '刷新中...' : '刷新'}
          </Button>
          <Button onClick={handleSync} disabled={syncing}>
            {syncing ? '同步中...' : '同步理财软件持仓'}
          </Button>
        </div>
      </div>
      {msg && <p className={`text-sm ${msg.type === 'ok' ? 'text-success' : 'text-danger'}`}>{msg.text}</p>}
      {error && <p className="text-sm text-danger">{error}</p>}

      {/* 对接状态 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-2">
          <h2 className="font-bold text-sm">理财软件对接</h2>
          {status ? (
            status.detected ? (
              <Badge variant="success">已检测到 finance.db</Badge>
            ) : (
              <Badge variant="warning">未检测到 finance.db</Badge>
            )
          ) : (
            <Badge>检测中...</Badge>
          )}
        </div>
        <p className="text-xs text-text-secondary leading-relaxed">
          {status === null
            ? '正在检测个人理财软件数据库...'
            : status.detected
              ? '已只读连接个人理财软件数据库（' + (status.db_path || 'finance.db') + '），点击右上角「同步理财软件持仓」立即同步；之后每小时自动同步。'
              : '未检测到个人理财软件数据库（AppData/Roaming/personal-finance/finance.db）。已保存的持仓仍可查看，安装理财软件后可随时同步。'}
        </p>
      </Card>

      {/* 资产配置摘要 */}
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
            title="暂无理财软件快照"
            description="点击右上角「同步理财软件持仓」后，账户与净值摘要将显示在这里。"
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
            description="点击右上角「同步理财软件持仓」从个人理财软件导入，或等待后续版本开放手动录入。"
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
                  <th className="px-3 py-2 text-center font-medium text-text-secondary">来源</th>
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
                    <tr key={h.symbol} className="border-t border-border hover:bg-primary-50">
                      <td className="px-3 py-2">
                        <div className="font-medium">{h.name || h.symbol}</div>
                        <div className="text-xs text-text-muted font-number">{h.symbol}</div>
                      </td>
                      <td className="px-3 py-2 text-center"><Badge variant={market === '港股' ? 'info' : 'default'}>{market}</Badge></td>
                      <td className="px-3 py-2 text-right font-number">{qty}</td>
                      <td className="px-3 py-2 text-right font-number">{fmtPrice(cost, market)}</td>
                      <td className="px-3 py-2 text-right font-number">{fmtPrice(price, market)}</td>
                      <td className="px-3 py-2 text-right font-number">{fmtMoney(mv)}</td>
                      <td className={'px-3 py-2 text-right font-number ' + upDownCls(pnl)}>{fmtMoney(pnl)}</td>
                      <td className={'px-3 py-2 text-right font-number ' + upDownCls(pnlPct)}>{fmtPct(pnlPct)}</td>
                      <td className="px-3 py-2 text-center">
                        <Badge variant={sourceVariant(h.source)}>{sourceLabel(h.source)}</Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="text-xs text-text-muted mt-2">
              现价为本地行情估值，可能与理财软件记录存在差异；最近同步时间 {holdings[0]?.sync_at ? fmtTime(holdings[0].sync_at) : '—'}
            </p>
          </div>
        )}
      </Card>

      {/* 手动录入（占位，后端接口未开放） */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">手动录入持仓</h2>
          <Badge variant="warning">规划中</Badge>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <div className="text-xs text-text-secondary mb-1">代码</div>
            <input className={inputCls + ' w-36'} placeholder="如 600519" disabled />
          </div>
          <div>
            <div className="text-xs text-text-secondary mb-1">市场</div>
            <select className={inputCls + ' w-24'} disabled>
              <option>A股</option>
            </select>
          </div>
          <div>
            <div className="text-xs text-text-secondary mb-1">数量（股）</div>
            <input className={inputCls + ' w-28'} placeholder="100" disabled />
          </div>
          <div>
            <div className="text-xs text-text-secondary mb-1">成本价（元）</div>
            <input className={inputCls + ' w-28'} placeholder="0.00" disabled />
          </div>
          <Button disabled>添加</Button>
        </div>
        <p className="text-xs text-text-muted mt-2">手动录入将在后续版本开放。当前请使用「同步理财软件持仓」从个人理财软件导入。</p>
        <p className="text-xs text-text-muted mt-1">提示：理财软件数据库为只读对接，本软件不会写入任何数据。</p>
      </Card>
    </div>
  );
}
