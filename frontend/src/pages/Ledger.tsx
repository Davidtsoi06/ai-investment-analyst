// S15 虚拟账本（纸面交易）：开户/买卖/持仓估值/一键从推荐买入 + 推荐回测统计（虚拟账本核心）
// 契约：/api/paper/{account,trade,portfolio,history,trade-from-recommendation}（后端实测契约）+ 复用 /api/recommend/{today,backtest}
import { useCallback, useEffect, useMemo, useState } from 'react';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import {
  getPaperAccount,
  getPaperHistory,
  getPaperPortfolio,
  getRecommendationsPerformance,
  getTodayRecommendations,
  openPaperAccount,
  paperTrade,
  paperTradeFromRecommendation,
  parseApiError,
} from '../services/api';
import type {
  BacktestRecentItem,
  PaperHistoryItem,
  PaperPosition,
  PaperPortfolio,
  RecommendItem,
} from '../services/api';

/** 兼容后端返回数组或 {items:[...]}/{list:[...]} 两种包装 */
function toList<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[];
  if (data && typeof data === 'object') {
    const d = data as Record<string, unknown>;
    if (Array.isArray(d.items)) return d.items as T[];
    if (Array.isArray(d.list)) return d.list as T[];
    if (Array.isArray(d.positions)) return d.positions as T[];
  }
  return [];
}

/** 涨跌配色（虚拟账本契约：涨绿跌红） */
function upDownCls(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return 'text-text';
  return v > 0 ? 'text-success' : 'text-danger';
}

/** 金额：元 → 万/亿 中文缩写 */
function fmtMoney(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 1e8) return '¥' + (v / 1e8).toFixed(2) + ' 亿';
  if (abs >= 1e4) return '¥' + (v / 1e4).toFixed(2) + ' 万';
  return '¥' + v.toFixed(2);
}

/** 比率归一化为百分数：0.667 → 66.7；66.7 → 66.7 */
function toPercent(v: number | null | undefined): number | null {
  if (v === null || v === undefined || Number.isNaN(v)) return null;
  return Math.abs(v) <= 1 ? v * 100 : v;
}

function fmtPct(v: number | null | undefined, digits = 1): string {
  const p = toPercent(v);
  return p === null ? '—' : (p > 0 ? '+' : '') + p.toFixed(digits) + '%';
}

/** 价格显示：A 股 2 位、港股 3 位 */
function fmtPrice(v: number | null | undefined, market?: string): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return v.toFixed(market === '港股' ? 3 : 2);
}

/** 时间：opened_at "2026-08-31 15:30:05" → "08-31 15:30" */
function fmtTime(s: string | null | undefined): string {
  if (!s) return '';
  // ISO（后端 utc_now，UTC）→ 北京时间；兼容 "2026-08-31 15:30:05" 本地格式
  if (s.includes('T')) {
    const d = new Date(s);
    if (!Number.isNaN(d.getTime())) {
      const bj = new Date(d.getTime() + 8 * 3600 * 1000);
      const p = (n: number) => String(n).padStart(2, '0');
      return p(bj.getMonth() + 1) + '-' + p(bj.getDate()) + ' ' + p(bj.getHours()) + ':' + p(bj.getMinutes());
    }
  }
  const m = /(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})/.exec(s);
  if (m) return m[1].slice(5) + ' ' + m[2];
  return s.slice(0, 16);
}

function Stat({ label, value, cls = '' }: { label: string; value: string; cls?: string }) {
  return (
    <div className="bg-bg-secondary rounded px-3 py-2">
      <div className="text-xs text-text-secondary">{label}</div>
      <div className={'text-sm font-number mt-0.5 ' + cls}>{value}</div>
    </div>
  );
}

/** 结果状态 → 徽章 */
const OUTCOME_BADGE: Record<string, 'success' | 'danger' | 'warning' | 'default'> = {
  win: 'success',
  loss: 'danger',
  stop: 'warning',
  flat: 'default',
};
const OUTCOME_LABEL: Record<string, string> = { win: '胜', loss: '亏', stop: '止损', flat: '平' };

export default function Ledger() {
  // ---- 账户与持仓（/api/paper/portfolio 一次返回） ----
  const [portfolio, setPortfolio] = useState<PaperPortfolio | null>(null);
  const [opened, setOpened] = useState<boolean | null>(null); // null=加载中
  const [initialBalance, setInitialBalance] = useState<number | null>(null);
  const [accountError, setAccountError] = useState('');
  const [opening, setOpening] = useState(false);
  const [initialCash, setInitialCash] = useState('');

  // ---- 交易记录 ----
  const [history, setHistory] = useState<PaperHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  // ---- 今日推荐（一键买入） ----
  const [recs, setRecs] = useState<RecommendItem[]>([]);
  const [recLoading, setRecLoading] = useState(false);

  // ---- 手动交易表单 ----
  const [form, setForm] = useState({ symbol: '', market: 'A股', type: 'buy' as 'buy' | 'sell', quantity: '100' });
  const [trading, setTrading] = useState(false);

  // ---- 回测统计（虚拟账本核心） ----
  const [backtest, setBacktest] = useState<Record<string, unknown> | null>(null);
  const [btLoading, setBtLoading] = useState(false);

  // ---- 卖出数量（按 symbol） ----
  const [sellQty, setSellQty] = useState<Record<string, string>>({});

  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  const flash = (text: string, type: 'ok' | 'err' = 'ok') => {
    setMsg({ type, text });
    window.setTimeout(() => setMsg(null), 6000);
  };

  const loadAccount = useCallback(async () => {
    setAccountError('');
    const r = await getPaperAccount();
    if (r.ok && r.data) {
      const d = r.data as { opened?: boolean; account?: { balance?: number | null; initial_balance?: number | null } | null };
      setOpened(!!d.opened);
      if (d.opened && d.account) {
        const bal = d.account.balance ?? d.account.initial_balance ?? null;
        setInitialBalance(bal !== null && bal !== undefined ? Number(bal) : null);
      }
      if (!d.opened && (d as { reason?: string }).reason) setAccountError((d as { reason?: string }).reason || '');
    } else {
      setOpened(false);
      setAccountError('账户获取失败：' + parseApiError(r.error));
    }
  }, []);

  const loadPortfolio = useCallback(async () => {
    const r = await getPaperPortfolio();
    if (r.ok && r.data) {
      const d = r.data as PaperPortfolio;
      setPortfolio(d);
      if (d.ok === false && d.reason && d.balance === null) setAccountError(d.reason);
    } else {
      setPortfolio(null);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    const r = await getPaperHistory(50);
    setHistoryLoading(false);
    if (r.ok) setHistory(toList<PaperHistoryItem>(r.data));
    else setHistory([]);
  }, []);

  const loadRecs = useCallback(async () => {
    setRecLoading(true);
    const r = await getTodayRecommendations();
    setRecLoading(false);
    if (r.ok && r.data) {
      const d = r.data as { items?: unknown };
      setRecs(toList<RecommendItem>(d.items));
    } else {
      setRecs([]);
    }
  }, []);

  const loadBacktest = useCallback(async () => {
    setBtLoading(true);
    const r = await getRecommendationsPerformance();
    setBtLoading(false);
    if (r.ok && r.data) setBacktest(r.data as Record<string, unknown>);
    else setBacktest(null);
  }, []);

  useEffect(() => {
    loadAccount();
    loadPortfolio();
    loadHistory();
    loadRecs();
    loadBacktest();
  }, [loadAccount, loadPortfolio, loadHistory, loadRecs, loadBacktest]);

  const reloadAll = useCallback(async () => {
    await Promise.all([loadAccount(), loadPortfolio(), loadHistory()]);
  }, [loadAccount, loadPortfolio, loadHistory]);

  const handleOpen = async () => {
    const cash = initialCash.trim() === '' ? undefined : Number(initialCash);
    if (cash !== undefined && (!Number.isFinite(cash) || cash <= 0)) {
      flash('初始资金需为正数（留空 = 按画像投资金额中值）', 'err');
      return;
    }
    setOpening(true);
    setMsg(null);
    const r = await openPaperAccount(cash);
    setOpening(false);
    if (!r.ok) {
      flash('开户失败：' + parseApiError(r.error), 'err');
      return;
    }
    const d = r.data as { ok?: boolean; existing?: boolean; account?: { balance?: number | null; initial_balance?: number | null } } | undefined;
    if (d && d.ok === false) {
      flash('开户失败：后端返回异常', 'err');
      return;
    }
    const bal = d?.account?.balance ?? d?.account?.initial_balance ?? null;
    setInitialBalance(bal !== null && bal !== undefined ? Number(bal) : null);
    flash(d?.existing ? '虚拟账户已存在，直接使用' : '虚拟账户开户成功，初始资金 ' + fmtMoney(bal));
    await reloadAll();
  };

  /** 提交交易（手动买卖） */
  const submitTrade = async (input: { symbol: string; market: string; type: 'buy' | 'sell'; quantity: number }) => {
    if (opened !== true) {
      flash('请先开户再交易', 'err');
      return;
    }
    if (!input.symbol.trim()) {
      flash('请输入股票代码', 'err');
      return;
    }
    if (!Number.isInteger(input.quantity) || input.quantity <= 0) {
      flash('数量需为正整数（股）', 'err');
      return;
    }
    setTrading(true);
    setMsg(null);
    const r = await paperTrade({ symbol: input.symbol.trim(), market: input.market, type: input.type, quantity: input.quantity });
    setTrading(false);
    if (!r.ok) {
      flash('下单失败：' + parseApiError(r.error, '后端不可用'), 'err');
      return;
    }
    const d = r.data as { ok?: boolean; type?: string; symbol?: string; name?: string | null; quantity?: number; price?: number; reason?: string };
    if (d && d.ok === false) {
      flash('下单失败：' + (d.reason || '未知原因'), 'err');
      return;
    }
    const sideTxt = input.type === 'buy' ? '买入' : '卖出';
    flash(sideTxt + ' ' + (d?.name || input.symbol) + ' ' + input.quantity + ' 股成交'
      + (d?.price ? ' @ ' + fmtPrice(d.price, input.market) : ''));
    await reloadAll();
  };

  const handleManualTrade = () => {
    submitTrade({
      symbol: form.symbol,
      market: form.market,
      type: form.type,
      quantity: Number(form.quantity),
    });
  };

  /** 一键从推荐买入（后端按推荐入场中值价买 1 手，余额不足自动折算） */
  const handleRecBuy = async (rec: RecommendItem) => {
    if (opened !== true) {
      flash('请先开户再交易', 'err');
      return;
    }
    setTrading(true);
    setMsg(null);
    const r = await paperTradeFromRecommendation(rec.id);
    setTrading(false);
    if (!r.ok) {
      flash('买入失败：' + parseApiError(r.error, '后端不可用'), 'err');
      return;
    }
    const d = r.data as { ok?: boolean; reason?: string; symbol?: string; name?: string | null; quantity?: number; price?: number; balance?: number };
    if (d && d.ok === false) {
      flash('买入失败：' + (d.reason || '未知原因'), 'err');
      return;
    }
    flash('已按推荐买入 ' + (d?.name || rec.name || rec.symbol) + ' ' + (d?.quantity ?? '—') + ' 股'
      + (d?.price ? ' @ ' + fmtPrice(d.price, rec.market) : ''));
    await reloadAll();
  };

  /** 持仓卖出（默认全部） */
  const handleSell = (p: PaperPosition) => {
    const q = sellQty[p.symbol] !== undefined && sellQty[p.symbol] !== '' ? Number(sellQty[p.symbol]) : p.quantity;
    submitTrade({
      symbol: p.symbol,
      market: p.market || 'A股',
      type: 'sell',
      quantity: q,
    });
  };

  // ---- 回测统计派生 ----
  const btSummary = useMemo(() => (backtest?.summary ?? {}) as Record<string, unknown>, [backtest]);
  const btByType = useMemo(() => (backtest?.by_type ?? {}) as Record<string, Record<string, unknown>>, [backtest]);
  const btRecent = useMemo(() => toList<BacktestRecentItem>(backtest?.recent).slice(0, 8), [backtest]);
  const num = (v: unknown): number | null => (typeof v === 'number' ? v : null);

  const positions = useMemo<PaperPosition[]>(() => toList<PaperPosition>(portfolio?.positions), [portfolio]);
  const balance = num(portfolio?.balance);
  const totalAssets = num(portfolio?.total_assets);
  // 总盈亏 = 总资产 - 初始资金（初始资金取自开户响应；刷新页面前端保持）
  const profit = totalAssets !== null && initialBalance !== null ? totalAssets - initialBalance : null;
  const profitPct = totalAssets !== null && initialBalance !== null && initialBalance > 0 ? (totalAssets / initialBalance - 1) * 100 : null;

  const inputCls = 'border border-border rounded px-2 py-1.5 text-sm w-full focus:outline-none focus:border-primary-500 bg-white';
  const labelCls = 'text-xs text-text-secondary mb-1 block';

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-bold text-primary-900">虚拟账本</h2>
          <p className="text-xs text-text-muted mt-1">AI 推荐回测统计（核心）+ 模拟交易（纸面交易）· 虚拟资金练习，不影响真实账户 · 仅作学习参考，不构成投资建议</p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => { reloadAll(); loadRecs(); loadBacktest(); }}>
          刷新
        </Button>
      </div>
      {msg && <p className={'text-sm ' + (msg.type === 'ok' ? 'text-success' : 'text-danger')}>{msg.text}</p>}
      {accountError && <p className="text-sm text-danger">{accountError}</p>}

      {/* 账户总览 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">账户总览</h2>
          {opened === true && <span className="text-xs text-text-muted">初始资金 {fmtMoney(initialBalance)}</span>}
        </div>
        {opened === null ? (
          <p className="text-sm text-text-muted">加载中...</p>
        ) : opened !== true ? (
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-44">
              <label className={labelCls}>初始资金（元，留空=画像中值）</label>
              <input className={inputCls} type="number" min="10000" step="10000" placeholder="默认 30 万" value={initialCash} onChange={(e) => setInitialCash(e.target.value)} />
            </div>
            <Button onClick={handleOpen} disabled={opening}>
              {opening ? '开户中...' : '开通虚拟账户'}
            </Button>
            <p className="text-xs text-text-muted">不填时初始余额 = 画像投资金额中值（10 万以下→5 万、10-50 万→30 万、50-100 万→75 万、100 万以上→150 万）</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <Stat label="总资产" value={fmtMoney(totalAssets)} />
            <Stat label="可用余额" value={fmtMoney(balance)} />
            <Stat label="总盈亏" value={fmtMoney(profit)} cls={upDownCls(profit)} />
            <Stat label="收益率" value={fmtPct(profitPct)} cls={upDownCls(profitPct)} />
          </div>
        )}
      </Card>

      {/* 一键从推荐买入 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">一键从推荐买入</h2>
          <span className="text-xs text-text-muted">今日 AI 推荐 · 按推荐入场价买入 1 手（100 股，余额不足自动折算）</span>
        </div>
        {opened !== true ? (
          <p className="text-sm text-text-muted">请先在上方开通虚拟账户。</p>
        ) : recLoading && recs.length === 0 ? (
          <p className="text-sm text-text-muted">加载中...</p>
        ) : recs.length === 0 ? (
          <p className="text-sm text-text-muted">今日暂无推荐，可先到「推荐中心」生成，或使用下方手动交易。</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {recs.map((rec) => {
              const mid = rec.rec_price
                ?? (rec.entry_min != null && rec.entry_max != null ? (rec.entry_min + rec.entry_max) / 2 : null)
                ?? (rec.valuation_min != null && rec.valuation_max != null ? (rec.valuation_min + rec.valuation_max) / 2 : null);
              return (
                <div key={rec.id} className="border border-border rounded-lg p-3 flex flex-wrap items-center gap-x-3 gap-y-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-sm">{rec.name || rec.symbol}</span>
                      <span className="text-xs text-text-muted font-number">{rec.symbol}</span>
                      <Badge variant={rec.market === '港股' ? 'info' : 'default'}>{rec.market || 'A股'}</Badge>
                      <Badge variant={rec.rec_type === '短线' ? 'warning' : 'default'}>{rec.rec_type || '—'}</Badge>
                    </div>
                    <div className="text-xs text-text-secondary mt-1 font-number">
                      参考价 {fmtPrice(mid, rec.market)}
                      {rec.confidence != null && <span className="ml-2">置信度 {rec.confidence}%</span>}
                    </div>
                  </div>
                  <Button size="sm" onClick={() => handleRecBuy(rec)} disabled={trading}>
                    买入 1 手
                  </Button>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {/* 手动交易 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">手动交易</h2>
          <span className="text-xs text-text-muted">输入股票代码按实时行情价成交（A 股 1 手 = 100 股）</span>
        </div>
        {opened !== true ? (
          <p className="text-sm text-text-muted">请先开通虚拟账户。</p>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2 items-end">
            <div>
              <label className={labelCls}>代码</label>
              <input className={inputCls} placeholder="如 600519 / 00700" value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })} />
            </div>
            <div>
              <label className={labelCls}>市场</label>
              <select className={inputCls} value={form.market} onChange={(e) => setForm({ ...form, market: e.target.value })}>
                <option value="A股">A股</option>
                <option value="港股">港股</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>方向</label>
              <select className={inputCls} value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value as 'buy' | 'sell' })}>
                <option value="buy">买入</option>
                <option value="sell">卖出</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>数量（股）</label>
              <input className={inputCls} type="number" min="1" step="100" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} />
            </div>
            <div>
              <label className={labelCls}>&nbsp;</label>
              <Button onClick={handleManualTrade} disabled={trading} variant={form.type === 'buy' ? 'primary' : 'danger'} className="w-full">
                {trading ? '提交中...' : form.type === 'buy' ? '买入' : '卖出'}
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* 当前持仓 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">当前持仓</h2>
          <span className="text-xs text-text-muted">{positions.length + ' 只 · 现价实时估值'}</span>
        </div>
        {positions.length === 0 ? (
          <p className="text-sm text-text-muted">暂无持仓。可从今日推荐一键买入，或手动下单。</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-bg-secondary">
                  <th className="px-3 py-2 text-left font-medium text-text-secondary">股票</th>
                  <th className="px-3 py-2 text-right font-medium text-text-secondary">持仓（股）</th>
                  <th className="px-3 py-2 text-right font-medium text-text-secondary">成本</th>
                  <th className="px-3 py-2 text-right font-medium text-text-secondary">现价</th>
                  <th className="px-3 py-2 text-right font-medium text-text-secondary">市值</th>
                  <th className="px-3 py-2 text-right font-medium text-text-secondary">盈亏</th>
                  <th className="px-3 py-2 text-right font-medium text-text-secondary">盈亏率</th>
                  <th className="px-3 py-2 text-center font-medium text-text-secondary">卖出</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.symbol} className="border-t border-border hover:bg-primary-50">
                    <td className="px-3 py-2">
                      <div className="font-medium">{p.name || p.symbol}</div>
                      <div className="text-xs text-text-muted font-number">{p.symbol} <Badge variant={p.market === '港股' ? 'info' : 'default'}>{p.market || 'A股'}</Badge></div>
                    </td>
                    <td className="px-3 py-2 text-right font-number">{p.quantity}</td>
                    <td className="px-3 py-2 text-right font-number">{fmtPrice(p.avg_cost, p.market)}</td>
                    <td className="px-3 py-2 text-right font-number">{fmtPrice(p.price, p.market)}</td>
                    <td className="px-3 py-2 text-right font-number">{fmtMoney(num(p.market_value))}</td>
                    <td className={'px-3 py-2 text-right font-number ' + upDownCls(num(p.pnl))}>{fmtMoney(num(p.pnl))}</td>
                    <td className={'px-3 py-2 text-right font-number ' + upDownCls(num(p.pnl_pct))}>{fmtPct(num(p.pnl_pct))}</td>
                    <td className="px-3 py-2 text-center">
                      <div className="flex items-center justify-end gap-1.5">
                        <input
                          className={'w-20 text-right ' + inputCls}
                          type="number"
                          min="1"
                          value={sellQty[p.symbol] !== undefined ? sellQty[p.symbol] : String(p.quantity)}
                          onChange={(e) => setSellQty({ ...sellQty, [p.symbol]: e.target.value })}
                        />
                        <Button variant="danger" size="sm" onClick={() => handleSell(p)} disabled={trading}>
                          卖出
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* 推荐回测统计（虚拟账本核心） */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">推荐回测统计</h2>
          <span className="text-xs text-text-muted">AI 推荐记录自动回测 · 短线 5 交易日 / 长线 20 交易日窗口 · 完整统计见「推荐中心」</span>
        </div>
        {btLoading && !backtest ? (
          <p className="text-sm text-text-muted">加载中...</p>
        ) : !backtest ? (
          <p className="text-sm text-text-muted">暂无回测数据，生成推荐后自动统计。</p>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <Stat label="样本数" value={String(num(btSummary.count) ?? '—')} />
              <Stat label="胜率" value={fmtPct(num(btSummary.win_rate))} cls={upDownCls(num(btSummary.win_rate))} />
              <Stat label="平均收益" value={fmtPct(num(btSummary.avg_return))} cls={upDownCls(num(btSummary.avg_return))} />
              <Stat label="总收益" value={fmtPct(num(btSummary.total_return))} cls={upDownCls(num(btSummary.total_return))} />
            </div>
            {Object.keys(btByType).length > 0 && (
              <div className="flex flex-wrap gap-2">
                {Object.entries(btByType).map(([k, g]) => (
                  <div key={k} className="border border-border rounded px-3 py-2 text-xs">
                    <span className="text-text-secondary mr-2">{k}</span>
                    胜率 <span className={'font-number ' + upDownCls(num(g.win_rate))}>{fmtPct(num(g.win_rate))}</span>
                    <span className="text-text-secondary ml-2">均收</span> <span className={'font-number ' + upDownCls(num(g.avg_return))}>{fmtPct(num(g.avg_return))}</span>
                    <span className="text-text-muted ml-2">n={String(num(g.count) ?? '—')}</span>
                  </div>
                ))}
              </div>
            )}
            {btRecent.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-bg-secondary">
                      <th className="px-3 py-2 text-left font-medium text-text-secondary">日期</th>
                      <th className="px-3 py-2 text-left font-medium text-text-secondary">股票</th>
                      <th className="px-3 py-2 text-center font-medium text-text-secondary">类型</th>
                      <th className="px-3 py-2 text-right font-medium text-text-secondary">结果</th>
                      <th className="px-3 py-2 text-right font-medium text-text-secondary">收益</th>
                    </tr>
                  </thead>
                  <tbody>
                    {btRecent.map((it) => (
                      <tr key={it.id} className="border-t border-border hover:bg-primary-50">
                        <td className="px-3 py-2 text-xs font-number text-text-secondary">{(it.rec_date || '').slice(0, 10)}</td>
                        <td className="px-3 py-2">{it.name || it.symbol}</td>
                        <td className="px-3 py-2 text-center"><Badge variant={it.rec_type === '短线' ? 'warning' : 'default'}>{it.rec_type || '—'}</Badge></td>
                        <td className="px-3 py-2 text-center"><Badge variant={OUTCOME_BADGE[it.outcome || ''] || 'default'}>{OUTCOME_LABEL[it.outcome || ''] || it.outcome || '待结算'}</Badge></td>
                        <td className={'px-3 py-2 text-right font-number ' + upDownCls(num(it.result_pct))}>{fmtPct(num(it.result_pct))}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </Card>

      {/* 交易记录 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">交易记录</h2>
          <span className="text-xs text-text-muted">最近 50 笔 · 卖出含已实现盈亏</span>
        </div>
        {historyLoading && history.length === 0 ? (
          <p className="text-sm text-text-muted">加载中...</p>
        ) : history.length === 0 ? (
          <p className="text-sm text-text-muted">暂无交易记录。</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-bg-secondary">
                  <th className="px-3 py-2 text-left font-medium text-text-secondary">时间</th>
                  <th className="px-3 py-2 text-left font-medium text-text-secondary">股票</th>
                  <th className="px-3 py-2 text-center font-medium text-text-secondary">方向</th>
                  <th className="px-3 py-2 text-right font-medium text-text-secondary">数量</th>
                  <th className="px-3 py-2 text-right font-medium text-text-secondary">价格</th>
                  <th className="px-3 py-2 text-right font-medium text-text-secondary">金额</th>
                  <th className="px-3 py-2 text-right font-medium text-text-secondary">已实现盈亏</th>
                  <th className="px-3 py-2 text-center font-medium text-text-secondary">来源</th>
                  <th className="px-3 py-2 text-center font-medium text-text-secondary">状态</th>
                </tr>
              </thead>
              <tbody>
                {history.map((o) => (
                  <tr key={o.id} className="border-t border-border hover:bg-primary-50">
                    <td className="px-3 py-2 text-xs font-number text-text-secondary">{fmtTime(o.opened_at)}</td>
                    <td className="px-3 py-2">
                      <span className="font-medium">{o.name || o.symbol}</span>
                      <span className="text-xs text-text-muted font-number ml-1.5">{o.symbol}</span>
                    </td>
                    <td className="px-3 py-2 text-center">
                      <Badge variant={o.type === 'buy' ? 'danger' : 'success'}>{o.type === 'buy' ? '买入' : '卖出'}</Badge>
                    </td>
                    <td className="px-3 py-2 text-right font-number">{o.quantity}</td>
                    <td className="px-3 py-2 text-right font-number">{fmtPrice(o.price, o.market)}</td>
                    <td className="px-3 py-2 text-right font-number">{fmtMoney(num(o.amount))}</td>
                    <td className={'px-3 py-2 text-right font-number ' + upDownCls(num(o.pnl))}>{o.type === 'sell' ? fmtMoney(num(o.pnl)) : '—'}</td>
                    <td className="px-3 py-2 text-center">
                      {o.recommendation_id ? <Badge variant="info">推荐买入</Badge> : <span className="text-xs text-text-muted">手动</span>}
                    </td>
                    <td className="px-3 py-2 text-center">
                      <Badge variant={o.status === 'open' ? 'info' : 'default'}>{o.status === 'open' ? '持仓中' : o.status === 'closed' ? '已平仓' : (o.status || '—')}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
