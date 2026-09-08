// V1.1.3 我的股票池：表（组）= 一等实体——全部视图(分区)/单表视图(过滤) · 建空表/管理表 · 搜索式添加 · 池体检
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import Loading from '../components/ui/Loading';
import EmptyState from '../components/ui/EmptyState';
import KLineChart from '../components/KLineChart';
import {
  addWatchlistItem,
  analyzePoolAi,
  analyzeStockPool,
  createWatchGroup,
  deleteWatchGroup,
  deleteWatchlistItem,
  getKline,
  getQuote,
  getRelatedNews,
  getWatchGroups,
  getWatchlist,
  parseApiError,
  searchStock,
  updateWatchGroup,
  updateWatchlistGroup,
} from '../services/api';
import type { KlineBar, PoolAnalyzeItem, Quote, RelatedNewsItem, WatchGroup, WatchlistItem } from '../services/api';
import { fmtNum, toList, upDownCls } from '../lib/format';

const MARKET_LABEL: Record<string, string> = { A股: '限A股', 港股: '限港股', '': '不限市场' };

export default function Watchlist() {
  const [groups, setGroups] = useState<WatchGroup[]>([]);
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [active, setActive] = useState<string>('__all__'); // '__all__'=全部视图，否则表名
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  // 添加：搜索框 + 候选
  const [kw, setKw] = useState('');
  const [cands, setCands] = useState<{ symbol: string; name: string; market: string; price?: number | null }[]>([]);
  const [searching, setSearching] = useState(false);
  const [picked, setPicked] = useState<{ symbol: string; name: string; market: string } | null>(null);
  const [addGroup, setAddGroup] = useState('');
  const searchSeq = useRef(0);

  // 建表/管理对话框
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState({ name: '', market: '', note: '' });
  const [manageTarget, setManageTarget] = useState<WatchGroup | null>(null);
  const [manageForm, setManageForm] = useState({ name: '', market: '', note: '' });

  // 体检
  const [poolReport, setPoolReport] = useState<{ items: PoolAnalyzeItem[]; errors?: string[] } | null>(null);
  const [poolRunning, setPoolRunning] = useState(false);

  // 单只详情（走势）
  const [detail, setDetail] = useState<WatchlistItem | null>(null);
  const [klineBars, setKlineBars] = useState<KlineBar[]>([]);
  const [klineLoading, setKlineLoading] = useState(false);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [relatedNews, setRelatedNews] = useState<RelatedNewsItem[]>([]);
  const detailSeq = useRef(0);

  const flash = (text: string, type: 'ok' | 'err' = 'ok') => { setMsg({ type, text }); window.setTimeout(() => setMsg(null), 4000); };

  const load = useCallback(async () => {
    setLoading(true);
    const [g, w] = await Promise.all([getWatchGroups(), getWatchlist()]);
    setLoading(false);
    if (g.ok) setGroups(toList<WatchGroup>(g.data));
    if (w.ok) setItems(toList<WatchlistItem>(w.data));
  }, []);

  useEffect(() => { void load(); }, [load]);

  // 搜索候选（代码/名称/拼音 ≥2 字符）
  useEffect(() => {
    const q = kw.trim();
    if (q.length < 2) { setCands([]); return; }
    const seq = ++searchSeq.current;
    setSearching(true);
    searchStock(q).then((r) => { if (seq === searchSeq.current) setCands(r.ok ? (r.data || []) : []); }).catch(() => {}).finally(() => { if (seq === searchSeq.current) setSearching(false); });
  }, [kw]);

  const pick = (c: { symbol: string; name: string; market: string }) => { setPicked(c); setKw(c.name + '（' + c.symbol + '）'); setCands([]); };

  const addToPool = async () => {
    if (!picked) return;
    if (active === '__all__' && !addGroup.trim()) { flash('请先选择要加入的表（或直接进某个表添加）', 'err'); return; }
    const targetGroup = active === '__all__' ? addGroup.trim() : active;
    const gMeta = active === '__all__' ? groups.find((g) => g.name === targetGroup) : activeGroupMeta;
    if (gMeta?.market && picked.market && picked.market !== gMeta.market) {
      if (!window.confirm('表「' + targetGroup + '」仅限' + gMeta.market + '，而 ' + picked.name + ' 属' + picked.market + '。仍要加入？（之后此表会同时包含两个市场）')) return;
    }
    const r = await addWatchlistItem({ symbol: picked.symbol, market: picked.market, group_name: targetGroup });
    if (!r.ok) { flash('添加失败：' + parseApiError(r.error), 'err'); return; }
    flash('已加入「' + targetGroup + '」');
    setPicked(null); setKw(''); setAddGroup('');
    await load();
  };

  const runPoolAnalyze = async () => {
    setPoolRunning(true); setAiMap(null);
    const r = await analyzeStockPool();
    setPoolRunning(false);
    if (r.ok && r.data) setPoolReport({ items: (r.data.items as PoolAnalyzeItem[]) || [], errors: (r.data.errors as string[]) || [] });
    else setPoolReport({ items: [], errors: [parseApiError(r.error)] });
  };

  // V1.1.6：AI 深度点评（独立按钮；结果覆盖建议列并带 ✨AI 标识）
  const [aiRunning, setAiRunning] = useState(false);
  const [aiMap, setAiMap] = useState<Record<string, { action: string; reason: string }> | null>(null);
  const runPoolAi = async () => {
    if (!poolReport) return;
    setAiRunning(true);
    const r = await analyzePoolAi();
    setAiRunning(false);
    if (r.ok && r.data && r.data.ok) {
      const m: Record<string, { action: string; reason: string }> = {};
      for (const it of (r.data.items || [])) m[it.symbol] = { action: it.action, reason: it.reason };
      setAiMap(m);
      flash('✨ AI 深度点评完成（建议仅供参考）');
    } else {
      const d = r.data as { reason?: string } | undefined;
      flash('AI 点评不可用：' + (d?.reason || parseApiError(r.error)), 'err');
    }
  };

  const saveGroup = async () => {
    const name = createForm.name.trim();
    if (!name) { flash('请输入表名', 'err'); return; }
    const r = await createWatchGroup({ name, market: createForm.market, note: createForm.note });
    setCreateOpen(false); setCreateForm({ name: '', market: '', note: '' });
    if (!r.ok || (r.data as { ok?: boolean })?.ok === false) { flash('建表失败：' + (((r.data as { reason?: string })?.reason) || parseApiError(r.error)), 'err'); return; }
    flash('已创建空表「' + name + '」');
    await load(); setActive(name);
  };

  const saveManage = async () => {
    if (!manageTarget) return;
    const r = await updateWatchGroup(manageTarget.name, { name: manageForm.name.trim() || undefined, market: manageForm.market, note: manageForm.note });
    setManageTarget(null);
    if (!r.ok || (r.data as { ok?: boolean })?.ok === false) { flash('保存失败：' + (((r.data as { reason?: string })?.reason) || parseApiError(r.error)), 'err'); return; }
    flash('表已更新');
    await load();
  };

  const removeGroup = async (g: WatchGroup) => {
    if (!window.confirm('删除表「' + g.name + '」及其中的 ' + (g.count ?? 0) + ' 只股票？')) return;
    const r = await deleteWatchGroup(g.name);
    setManageTarget(null);
    if (!r.ok) { flash('删除失败：' + parseApiError(r.error), 'err'); return; }
    flash('已删除表「' + g.name + '」');
    await load();
    if (active === g.name) setActive('__all__');
  };

  const moveItem = async (it: WatchlistItem, group: string) => {
    const r = await updateWatchlistGroup(it.id, group);
    if (r.ok) flash('已移至「' + group + '」'); else flash('移动失败：' + parseApiError(r.error), 'err');
    await load();
  };

  const removeItem = async (it: WatchlistItem) => {
    if (!window.confirm('从池中删除 ' + (it.name || it.symbol) + '？')) return;
    const r = await deleteWatchlistItem(it.id);
    if (r.ok) flash('已删除'); else flash('删除失败：' + parseApiError(r.error), 'err');
    await load();
  };

  const showDetail = async (it: WatchlistItem) => {
    setDetail(it); setKlineBars([]); setRelatedNews([]);
    const seq = ++detailSeq.current;
    setKlineLoading(true);
    const [k, q, n] = await Promise.all([getKline(it.symbol, it.market || 'A股', 120), getQuote(it.symbol, it.market || 'A股'), getRelatedNews(it.name || it.symbol)]);
    if (seq !== detailSeq.current) return;
    setKlineLoading(false);
    if (k.ok) setKlineBars(toList<KlineBar>(k.data));
    if (q.ok && q.data) setQuote(q.data as Quote);
    if (n.ok) setRelatedNews(toList<RelatedNewsItem>(n.data));
  };

  // 分组视图数据
  const groupItems = useMemo(() => {
    if (active === '__all__') return null;
    return items.filter((i) => (i.group_name || '默认') === active);
  }, [active, items]);
  const activeGroupMeta = useMemo(() => groups.find((g) => g.name === active), [groups, active]);

  const renderRow = (it: WatchlistItem) => {
    const market = it.market || 'A股';
    return (
      <div key={it.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2 border-t border-border first:border-t-0">
        <button onClick={() => void showDetail(it)} className="text-left">
          <span className="font-medium text-sm hover:text-primary-600">{it.name || it.symbol}</span>
          <span className="text-xs text-text-muted font-number ml-2">{it.symbol}</span>
        </button>
        <Badge variant={market === '港股' ? 'info' : 'default'}>{market}</Badge>
        <span className="text-xs text-text-muted ml-auto flex items-center gap-2">
          <button className="text-primary-600 hover:text-primary-700" onClick={() => void showDetail(it)}>走势</button>
          {active !== '__all__' && groups.length > 1 && (
            <select value="" onChange={(e) => { if (e.target.value) void moveItem(it, e.target.value); }} className="text-xs border border-border rounded px-1 py-0.5 bg-white">
              <option value="">移至…</option>
              {groups.filter((g) => g.name !== active).map((g) => <option key={g.name} value={g.name}>{g.name}</option>)}
            </select>
          )}
          <button className="text-danger hover:opacity-70" onClick={() => void removeItem(it)}>删除</button>
        </span>
      </div>
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-primary-900">我的股票池</h1>
          <p className="text-xs text-text-muted mt-1">先建表（A股表/港股表…）再往里放股票；AI 推荐/资讯/体检都从这里出发。</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => void load()} disabled={loading}>刷新</Button>
          <Button size="sm" onClick={runPoolAnalyze} disabled={poolRunning}>{poolRunning ? '分析中...' : (poolReport ? '重新体检' : '🔍 分析我的股票池')}</Button>
        </div>
      </div>
      {msg && <p className={"text-sm " + (msg.type === 'ok' ? 'text-success' : 'text-danger')}>{msg.text}</p>}

      {/* Tab：全部 + 各表 + 新建表 */}
      <div className="flex flex-wrap items-center gap-1.5">
        <button onClick={() => setActive('__all__')} className={"px-3 py-1.5 rounded-lg border text-sm " + (active === '__all__' ? 'border-primary-500 bg-primary-50 text-primary-700 font-medium' : 'border-border hover:border-primary-300')}>全部（{items.length}）</button>
        {groups.map((g) => (
          <button key={g.name} onClick={() => setActive(g.name)} className={"px-3 py-1.5 rounded-lg border text-sm " + (active === g.name ? 'border-primary-500 bg-primary-50 text-primary-700 font-medium' : 'border-border hover:border-primary-300')}>
            {g.name}{g.market ? ' · ' + MARKET_LABEL[g.market] : ''}（{g.count ?? 0}）
          </button>
        ))}
        <button onClick={() => { setCreateForm({ name: '', market: '', note: '' }); setCreateOpen(true); }} title="新建空表" className="px-2.5 py-1.5 rounded-lg border border-dashed border-primary-300 text-primary-600 text-lg leading-none hover:bg-primary-50">＋</button>
      </div>

      {/* 体检结果 */}
      {poolReport && (
        <Card>
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <h2 className="font-bold text-sm">股票池体检</h2>
            <span className="text-xs text-text-muted">位置 + RSI + 最新资讯 + 操作建议（仅供参考）</span>
            {(poolReport.errors || []).length > 0 && <span className="text-xs text-warning">⚠ {(poolReport.errors || []).length} 条跳过</span>}
            <span className="ml-auto">
              <Button variant="secondary" size="sm" onClick={() => void runPoolAi()} disabled={aiRunning || poolRunning || poolReport.items.length === 0}>
                {aiRunning ? 'AI 点评中…' : (aiMap ? '✨ 重新 AI 点评' : '✨ AI 深度点评')}
              </Button>
            </span>
          </div>
          {poolReport.items.length === 0 && (poolReport.errors || []).length === 0 ? (
            <p className="text-sm text-text-secondary">池内暂无股票，请先添加。</p>
          ) : (
            <div className="space-y-1">
              {poolReport.items.map((it) => {
                const ai = aiMap ? aiMap[it.symbol] : undefined;
                const action = ai?.action || it.action;
                const reason = ai?.reason || it.action_reason || it.reason || '';
                const actCls = action === '买入' ? 'text-success' : action === '减仓' ? 'text-danger' : action === '持有' ? 'text-primary-600' : 'text-text-secondary';
                return (
                <div key={it.symbol + it.market} className="border-t border-border pt-1.5 first:border-t-0 first:pt-0 text-sm">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
                    <span className="text-xs text-text-muted w-20 truncate">{it.group || '默认'}</span>
                    <span className="font-medium">{it.name}</span>
                    <span className="text-xs text-text-muted font-number">{it.symbol}</span>
                    <span className="font-number">{it.price != null ? fmtNum(it.price, it.market === '港股' ? 3 : 2) : '—'}</span>
                    {it.position === 'high' && <Badge variant="danger">高位</Badge>}
                    {it.position === 'mid' && <Badge variant="info">中位</Badge>}
                    {it.position === 'low' && <Badge variant="success">低位</Badge>}
                    {it.sentiment && <span className={"text-xs " + (it.sentiment === '利多' ? 'text-success' : it.sentiment === '利空' ? 'text-danger' : 'text-text-muted')}>{it.sentiment === '利多' ? '📈' : it.sentiment === '利空' ? '📉' : '➖'} {it.sentiment}</span>}
                    <span className={"font-medium " + actCls} title={reason}>{action || '—'}{ai ? ' ✨AI' : ''}</span>
                    {!ai && it.verdict && <span className="text-xs text-text-muted">{it.verdict}</span>}
                  </div>
                  <div className="text-xs text-text-muted mt-0.5 pl-1">
                    {reason}
                    {(it.news || []).length > 0 && (
                      <span className="block mt-0.5">
                        {(it.news || []).slice(0, 3).map((n, i) => (
                          <span key={i} className="inline-flex items-center gap-1 mr-3">
                            {n.url ? (
                              <a href="#" onClick={(e) => { e.preventDefault(); window.app?.openExternal(n.url || ''); }} className="text-primary-600 hover:underline">📰 {n.title}</a>
                            ) : <span>📰 {n.title}</span>}
                          </span>
                        ))}
                      </span>
                    )}
                  </div>
                </div>
                );
              })}
              {(poolReport.errors || []).map((e, i) => <p key={'e' + i} className="text-xs text-warning">⚠ {e}</p>)}
            </div>
          )}
        </Card>
      )}

      {/* 添加区：搜索式 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[220px]">
            <input value={kw} onChange={(e) => setKw(e.target.value)} placeholder="输入代码 / 名称 / 拼音首字母搜索，如 600519 / 百度 / bd"
              className="w-full rounded border border-border px-3 py-2 text-sm outline-none focus:border-primary-500" />
            {searching && <div className="absolute right-2 top-2.5 text-xs text-text-muted">搜索中...</div>}
            {cands.length > 0 && (
              <div className="absolute z-20 mt-1 w-full rounded border border-border bg-surface shadow-lg max-h-64 overflow-auto">
                {cands.map((c) => {
                  const targetMarket = active !== '__all__' ? activeGroupMeta?.market : (groups.find((g) => g.name === addGroup)?.market || '');
                  const mis = targetMarket && c.market && c.market !== targetMarket;
                  return (
                    <button key={c.symbol + c.market} onClick={() => pick(c)}
                      className={"w-full text-left px-3 py-2 flex items-center gap-2 text-sm " + (mis ? 'opacity-50 hover:bg-transparent' : 'hover:bg-primary-50')}>
                      <span className={"font-medium " + (mis ? 'line-through decoration-text-muted/60' : '')}>{c.name}</span>
                      <span className="text-xs text-text-muted font-number">{c.symbol}</span>
                      <Badge variant={c.market === '港股' ? 'info' : 'default'}>{c.market}</Badge>
                      <span className="ml-auto flex items-center gap-2">
                        {mis && <span className="text-[10px] text-warning">非本表市场</span>}
                        <span className="text-xs text-text-muted font-number">{c.price != null ? fmtNum(c.price, c.market === '港股' ? 3 : 2) : ''}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
          <select value={active === '__all__' ? addGroup : active} onChange={(e) => setAddGroup(e.target.value)} disabled={active !== '__all__'} className="rounded border border-border px-2 py-2 text-sm bg-white">
            {active !== '__all__' ? <option value={active}>{active}</option> : (<>
              <option value="">加入表…</option>
              {groups.length === 0 && <option value="默认">默认</option>}
              {groups.map((g) => <option key={g.name} value={g.name}>{g.name}{g.market ? '（' + MARKET_LABEL[g.market] + '）' : ''}</option>)}
            </>)}
          </select>
          <Button size="sm" disabled={!picked || (active === '__all__' && !addGroup)} onClick={addToPool}>加入 {picked ? picked.name : ''}</Button>
        </div>
        <p className="text-xs text-text-muted mt-2">选择候选后点「加入」；表限市场时会提示错配股票。</p>
      </Card>

      {/* 列表区 */}
      <Card>
        {active === '__all__' ? (
          <div className="space-y-4">
            {groups.length === 0 && items.length === 0 && (<EmptyState icon="⭐" title="还没有任何表" description="点右上角「＋」新建空表（如 A股表 / 港股观察），或直接在搜索框添加股票。" className="py-6" />)}
            {groups.map((g) => {
              const gItems = items.filter((i) => (i.group_name || '默认') === g.name);
              return (
                <div key={g.name} className="rounded border border-border">
                  <div className="flex items-center gap-2 px-3 py-2 bg-bg-secondary/60 rounded-t">
                    <button onClick={() => setActive(g.name)} className="font-bold text-sm text-primary-900 hover:text-primary-600">{g.name}</button>
                    {g.market ? <Badge variant="default">{MARKET_LABEL[g.market]}</Badge> : null}
                    <span className="text-xs text-text-muted">{gItems.length} 只</span>
                    {gItems.length === 0 && <span className="text-xs text-text-muted">（空表）</span>}
                    <span className="ml-auto flex items-center gap-2">
                      {gItems.length > 0 && <button className="text-xs text-primary-600 hover:text-primary-700" onClick={() => setActive(g.name)}>进入 ›</button>}
                      <button className="text-xs text-text-secondary hover:text-primary-600" onClick={() => { setManageTarget(g); setManageForm({ name: g.name, market: g.market || '', note: g.note || '' }); }}>管理</button>
                    </span>
                  </div>
                  {gItems.length === 0 ? <p className="px-3 py-4 text-center text-xs text-text-muted">这个表还是空的——在下方搜索添加第一只股票，或点「＋」规划新表</p> : <div className="px-3 pb-1">{gItems.map(renderRow)}</div>}
                </div>
              );
            })}
          </div>
        ) : (
          <div>
            <div className="flex flex-wrap items-center gap-2 mb-2">
              <button onClick={() => setActive('__all__')} className="text-xs text-primary-600 hover:text-primary-700">← 返回全部</button>
              <h2 className="font-bold text-sm">{active} ｜ {groupItems?.length ?? 0} 只</h2>
              {activeGroupMeta?.market ? <Badge variant="default">{MARKET_LABEL[activeGroupMeta.market]}</Badge> : null}
              <span className="ml-auto flex items-center gap-2">
                <Button variant="secondary" size="sm" onClick={() => { setManageTarget(activeGroupMeta || { name: active, market: '', note: '' }); setManageForm({ name: active, market: activeGroupMeta?.market || '', note: activeGroupMeta?.note || '' }); }}>管理表</Button>
              </span>
            </div>
            {(groupItems || []).length === 0 ? <EmptyState icon="📭" title="这个表还是空的" description="在下方搜索框找股票加入本表。" className="py-6" /> : <div>{ (groupItems || []).map(renderRow) }</div>}
          </div>
        )}
      </Card>

      {/* 建空表对话框 */}
      {createOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setCreateOpen(false)}>
          <div className="bg-surface rounded-xl shadow-xl w-full max-w-sm p-5" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-base font-bold text-primary-900 mb-3">新建表</h3>
            <div className="space-y-3">
              <div><div className="text-xs text-text-secondary mb-1">表名 *（如 A股表 / 港股观察）</div><input value={createForm.name} onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })} className="w-full rounded border border-border px-3 py-2 text-sm outline-none focus:border-primary-500" placeholder="A股表" /></div>
              <div><div className="text-xs text-text-secondary mb-1">市场范围（可选；不限 = 可混放 A股+港股）</div>
                <select value={createForm.market} onChange={(e) => setCreateForm({ ...createForm, market: e.target.value })} className="w-full rounded border border-border px-3 py-2 text-sm bg-white"><option value="">不限（可混合 A股 + 港股）</option><option value="A股">仅 A股</option><option value="港股">仅 港股</option></select></div>
              <div><div className="text-xs text-text-secondary mb-1">备注（可选）</div><input value={createForm.note} onChange={(e) => setCreateForm({ ...createForm, note: e.target.value })} className="w-full rounded border border-border px-3 py-2 text-sm outline-none focus:border-primary-500" placeholder="如：打算配置的港股科技" /></div>
            </div>
            <div className="mt-4 flex justify-end gap-2"><Button variant="secondary" size="sm" onClick={() => setCreateOpen(false)}>取消</Button><Button size="sm" onClick={saveGroup} disabled={!createForm.name.trim()}>创建</Button></div>
          </div>
        </div>
      )}

      {/* 管理表对话框 */}
      {manageTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setManageTarget(null)}>
          <div className="bg-surface rounded-xl shadow-xl w-full max-w-sm p-5" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-base font-bold text-primary-900 mb-3">管理表「{manageTarget.name}」</h3>
            <div className="space-y-3">
              <div><div className="text-xs text-text-secondary mb-1">表名</div><input value={manageForm.name} onChange={(e) => setManageForm({ ...manageForm, name: e.target.value })} className="w-full rounded border border-border px-3 py-2 text-sm outline-none focus:border-primary-500" /></div>
              <div><div className="text-xs text-text-secondary mb-1">市场范围</div><select value={manageForm.market} onChange={(e) => setManageForm({ ...manageForm, market: e.target.value })} className="w-full rounded border border-border px-3 py-2 text-sm bg-white"><option value="">不限（可混合）</option><option value="A股">仅 A股</option><option value="港股">仅 港股</option></select></div>
              <div><div className="text-xs text-text-secondary mb-1">备注</div><input value={manageForm.note} onChange={(e) => setManageForm({ ...manageForm, note: e.target.value })} className="w-full rounded border border-border px-3 py-2 text-sm outline-none focus:border-primary-500" /></div>
            </div>
            <div className="mt-4 flex items-center justify-between">
              <Button variant="danger" size="sm" onClick={() => void removeGroup(manageTarget)}>删除表</Button>
              <div className="flex gap-2"><Button variant="secondary" size="sm" onClick={() => setManageTarget(null)}>取消</Button><Button size="sm" onClick={saveManage} disabled={!manageForm.name.trim()}>保存</Button></div>
            </div>
          </div>
        </div>
      )}

      {/* 单只详情（走势） */}
      {detail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setDetail(null)}>
          <div className="bg-surface rounded-xl shadow-xl w-full max-w-2xl p-5 max-h-[85vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 mb-3">
              <span className="text-lg font-bold text-primary-900">{detail.name}</span><span className="text-xs text-text-muted font-number">{detail.symbol}</span><Badge variant={detail.market === '港股' ? 'info' : 'default'}>{detail.market || 'A股'}</Badge>
              {quote && <span className="ml-auto text-sm font-number">{fmtNum(quote.price, quote.market === '港股' ? 3 : 2)} <span className={"text-xs " + upDownCls(quote.change_pct)}>{quote.change_pct != null ? (quote.change_pct > 0 ? '+' : '') + quote.change_pct.toFixed(2) + '%' : ''}</span></span>}
              <button onClick={() => setDetail(null)} className="text-text-muted hover:text-text text-lg leading-none">×</button>
            </div>
            {klineLoading ? <Loading /> : klineBars.length > 0 ? <KLineChart bars={klineBars} height={320} /> : <p className="text-sm text-text-muted">K线暂不可用</p>}
            {relatedNews.length > 0 && (<div className="mt-3"><div className="text-xs font-bold text-text-secondary mb-1">关联资讯</div><div className="space-y-1">{relatedNews.slice(0, 5).map((n, i) => <p key={i} className="text-xs text-text-secondary">· {n.title}</p>)}</div></div>)}
          </div>
        </div>
      )}
    </div>
  );
}