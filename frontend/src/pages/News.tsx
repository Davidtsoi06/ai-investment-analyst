import { useEffect, useState } from 'react';
import Card from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import Loading from '../components/ui/Loading';
import EmptyState from '../components/ui/EmptyState';
import { api, parseApiError } from '../services/api';

interface NewsItem {
  id: number;
  title: string;
  url: string;
  source: string;
  market: string;
  summary: string;
  level: string;
  published_at: string;
  region?: string | null;
  related?: string[];
  holding_related?: boolean;
}

interface Premarket {
  date?: string;
  content?: string;
  fetched?: number;
  saved?: number;
  pushed?: boolean;
  created_at?: string;
}

const LEVEL_BADGE: Record<string, 'danger' | 'warning' | 'default'> = { '重大': 'danger', '中等': 'warning', '一般': 'default' };
const REGION_MARK: Record<string, string> = { '美国': '🇺🇸', '英国': '🇬🇧', '日本': '🇯🇵', '韩国': '🇰🇷' };

// V1.1.6 关注方向：预设（美股大方向 / A股港股主力）+ 自定义（本机保存）
interface Direction { id: string; name: string; words: string[] }
const PRESET_DIRECTIONS: Direction[] = [
  {
    id: 'us-macro', name: '美股大方向',
    words: ['美联储', '加息', '降息', '美债', '美股', '标普', '纳斯达克', '道琼斯', '美元指数', '英伟达', '苹果公司', '特斯拉', '微软', '谷歌', '亚马逊', 'OpenAI', '台积电', '美光', '高盛', '摩根'],
  },
  {
    id: 'cn-hk-blue', name: 'A股港股主力',
    words: ['贵州茅台', '五粮液', '宁德时代', '比亚迪', '招商银行', '工商银行', '建设银行', '中国平安', '中国石油', '中国移动', '长江电力', '腾讯控股', '腾讯', '阿里巴巴', '阿里', '美团', '小米集团', '京东集团', '快手', '网易', '汇丰控股', '友邦保险', '香港交易所', '港交所', '中芯国际', '药明康德', '中信证券'],
  },
];
const LS_DIRS_KEY = 'news.directions.custom.v1';

function loadCustomDirs(): string[] {
  try {
    const raw = localStorage.getItem(LS_DIRS_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr.filter((x: unknown) => typeof x === 'string' && (x as string).trim()) as string[] : [];
  } catch { return []; }
}
function saveCustomDirs(dirs: string[]) {
  try { localStorage.setItem(LS_DIRS_KEY, JSON.stringify(dirs)); } catch { /* ignore */ }
}
/** 标题+一句话简述是否命中某组词 */
function hitWords(it: NewsItem, words: string[]): boolean {
  const hay = ((it.title || '') + ' ' + (it.summary || '')).toLowerCase();
  return words.some((w) => !!w && hay.includes(w.toLowerCase()));
}

/** 打开原文（桌面经系统浏览器；网页新窗口） */
function openUrl(url: string) {
  if (window.app?.openExternal) void window.app.openExternal(url);
  else window.open(url, '_blank', 'noopener');
}

function NewsRow({ it }: { it: NewsItem }) {
  const isOverseas = it.region && it.region !== 'cn';
  const title = it.title || '';
  return (
    <div className="py-2.5">
      <div className="flex items-center gap-2 flex-wrap">
        <Badge variant={LEVEL_BADGE[it.level] || 'default'}>{it.level}</Badge>
        {isOverseas && <span title={'海外源 · ' + it.region}>{REGION_MARK[it.region || ''] || '🌍'} {it.region}</span>}
        <span className="text-xs text-text-muted">{it.source || it.market}</span>
        {Array.isArray(it.related) && it.related.length > 0 && (
          <Badge variant="info">📌 {it.related.slice(0, 3).join('、')}</Badge>
        )}
        {!isOverseas && it.holding_related && <Badge variant="info">持仓相关 ★</Badge>}
        {isOverseas && <span className="text-xs text-text-muted">英文原文 · 标题已译</span>}
        <span className="text-xs text-text-muted ml-auto">{(it.published_at || '').slice(5, 16)}</span>
      </div>
      <div className="text-sm font-medium text-text mt-1">{title}</div>
      {it.summary && <p className="text-xs text-text-secondary mt-0.5 line-clamp-2">{it.summary}</p>}
      <button onClick={() => openUrl(it.url)} className="text-xs text-primary-600 hover:text-primary-700 mt-1">
        {isOverseas ? '查看原文（原网站）↗' : '查看原文 ↗'}
      </button>
    </div>
  );
}

function NewsSection({ title, items, icon, emptyText }: { title: string; items: NewsItem[]; icon: string; emptyText: string }) {
  return (
    <Card>
      <div className="flex items-center gap-2 mb-2">
        <h2 className="font-bold text-sm">{icon} {title}</h2>
        {items.length > 0 && <span className="text-xs text-text-muted">{items.length} 条</span>}
      </div>
      {items.length === 0 ? (
        <EmptyState icon={icon} title="暂无内容" description={emptyText} className="py-6" />
      ) : (
        <div className="divide-y divide-border">
          {items.slice(0, 20).map((it) => <NewsRow key={it.id} it={it} />)}
        </div>
      )}
    </Card>
  );
}

export default function News() {
  const [premarket, setPremarket] = useState<Premarket | null>(null);
  const [items, setItems] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingList, setLoadingList] = useState(false);
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  // V1.1.6：关注方向（预设开关 + 自定义；抓取前弹窗编辑）
  const [dirOpen, setDirOpen] = useState(false);
  const [presetOn, setPresetOn] = useState<Record<string, boolean>>({ 'us-macro': true, 'cn-hk-blue': true });
  const [customDirs, setCustomDirs] = useState<string[]>(() => loadCustomDirs());
  const [dirInput, setDirInput] = useState('');

  const load = async () => {
    setLoadingList(true);
    const [p, l] = await Promise.all([
      api<Premarket>('GET', '/api/news/premarket/today'),
      api<NewsItem[]>('GET', '/api/news/latest?limit=60'),
    ]);
    setLoadingList(false);
    if (p.ok) setPremarket(p.data as Premarket);
    if (l.ok) setItems((l.data as NewsItem[]) || []);
  };

  useEffect(() => { load(); }, []);

  // 分区：池相关（related/持仓）> 海外 > 全市场中文
  const poolItems = items.filter((it) => (Array.isArray(it.related) && it.related.length > 0) || it.holding_related);
  const overseas = items.filter((it) => it.region && it.region !== 'cn' && !poolItems.includes(it));
  const market = items.filter((it) => (!it.region || it.region === 'cn') && !poolItems.includes(it));

  // V1.1.6：🎯 关注方向命中（标题+简述含关键词；预设开启项 + 自定义词）
  const dirHits: { it: NewsItem; names: string[] }[] = (() => {
    const enabled = PRESET_DIRECTIONS.filter((d) => presetOn[d.id]);
    const customWords: string[][] = customDirs.map((c) => c.split(/[\s,，、]+/).filter(Boolean));
    const out: { it: NewsItem; names: string[] }[] = [];
    for (const it of items) {
      const names: string[] = [];
      for (const d of enabled) if (hitWords(it, d.words)) names.push(d.name);
      for (let i = 0; i < customWords.length; i++) {
        if (customWords[i].length && hitWords(it, customWords[i])) names.push('自定义·' + customDirs[i].slice(0, 12));
      }
      if (names.length) out.push({ it, names });
    }
    return out;
  })();

  const refresh = async () => {
    setLoading(true);
    setMsg({ type: 'ok', text: '正在抓取中文源（约 3~10 秒），随后抓取海外源（美/英/日/韩）...' });
    const r = await api<{ ok: boolean; fetched?: number; saved?: number; reason?: string }>('POST', '/api/news/premarket/run');
    const cnMsg = r.ok && r.data?.ok ? `中文源整合完成：抓取 ${r.data.fetched} 条 / 新增 ${r.data.saved} 条` : ('中文源失败：' + (r.data?.reason || parseApiError(r.error)));
    setMsg({ type: 'ok', text: cnMsg + '；海外源抓取中...' });
    const o = await api<{ fetched?: number; saved?: number; failed_sources?: string[] }>('POST', '/api/news/fetch-overseas');
    const fail = (o.data?.failed_sources || []).length ? '（不可达：' + (o.data?.failed_sources || []).join('、') + '）' : '';
    setMsg({
      type: (r.ok && r.data?.ok) || o.ok ? 'ok' : 'err',
      text: cnMsg + (o.ok ? `；海外源新增 ${o.data?.saved ?? 0} 条${fail}` : '；海外源抓取失败'),
    });
    await load();
    setLoading(false);
    setTimeout(() => setMsg(null), 6000);
  };

  const renderPremarket = (content: string) =>
    content.split('\n').map((line, i) => {
      let cls = 'text-text-secondary';
      if (line.startsWith('📰') || line.includes('━━')) cls = 'font-bold text-primary-900';
      else if (line.startsWith('🔴')) cls = 'text-danger';
      else if (line.startsWith('🟡')) cls = 'text-warning';
      else if (line.startsWith('🟢')) cls = 'text-success';
      return <p key={i} className={`text-sm leading-6 ${cls}`}>{line}</p>;
    });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold text-primary-900">资讯看板</h1>
          {premarket?.pushed && <Badge variant="success">已推送</Badge>}
        </div>
        <Button size="sm" onClick={() => setDirOpen(true)} disabled={loading}>
          {loading ? '抓取整合中（约 10~30 秒）...' : '🎯 抓取最新资讯'}
        </Button>
      </div>
      {msg && <p className={`text-sm ${msg.type === 'ok' ? 'text-success' : 'text-danger'}`}>{msg.text}</p>}

      <Card>
        <div className="flex items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">今日盘前资讯</h2>
          {premarket?.date && <span className="text-xs text-text-muted">{premarket.date}{premarket.fetched ? ` · 抓取 ${premarket.fetched} 条` : ''}</span>}
        </div>
        {premarket?.content ? renderPremarket(premarket.content) : (
          <EmptyState icon="📰" title="今日尚无盘前资讯" description="点击右上角「抓取最新资讯」获取今日盘前整合内容。" className="py-6" />
        )}
      </Card>

      {/* V1.1.6 🎯 关注方向：命中标题/简述关键词的资讯集中展示 */}
      {dirHits.length > 0 && (
        <Card>
          <div className="flex items-center gap-2 mb-2">
            <h2 className="font-bold text-sm">🎯 关注方向</h2>
            <span className="text-xs text-text-muted">{dirHits.length} 条（标题+简述命中）</span>
          </div>
          <div className="divide-y divide-border">
            {dirHits.slice(0, 30).map(({ it, names }) => (
              <div key={it.id} className="py-2.5">
                <div className="flex items-center gap-2 flex-wrap">
                  {names.map((n) => <Badge key={n} variant="info">🎯 {n}</Badge>)}
                  <span className="text-xs text-text-muted ml-auto">{(it.published_at || '').slice(5, 16)}</span>
                </div>
                <div className="text-sm font-medium text-text mt-1">{it.title}</div>
                {it.summary && <p className="text-xs text-text-secondary mt-0.5 line-clamp-2">{it.summary}</p>}
                <button onClick={() => openUrl(it.url)} className="text-xs text-primary-600 hover:text-primary-700 mt-1">查看原文 ↗</button>
              </div>
            ))}
          </div>
        </Card>
      )}

      {loadingList && items.length === 0 ? (
        <Loading />
      ) : (
        <>
          <NewsSection icon="📌" title="我的股票池相关" items={poolItems}
            emptyText="暂无与您持仓/股票池相关的资讯——在「我的股票池」添加观察股后，相关新闻会优先展示在这里。" />
          <NewsSection icon="🌍" title="海外市场（自动翻译为中文标题，点击查看原网站）" items={overseas}
            emptyText="海外源暂未抓到内容（可点右上角「抓取最新资讯」；英国/日本源视网络可达性而定）。" />
          <NewsSection icon="🗞️" title="全市场要闻（AI 分级）" items={market} emptyText="可点击右上角「抓取最新资讯」手动抓取整合。" />
        </>
      )}

      {/* V1.1.6 抓取弹窗：每次抓取前选择关注方向 */}
      {dirOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setDirOpen(false)}>
          <div className="bg-surface rounded-xl shadow-xl w-full max-w-md p-5" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-base font-bold text-primary-900 mb-1">🎯 选择关注方向后抓取</h3>
            <p className="text-xs text-text-muted mb-3">命中的资讯会集中展示在看板顶部「关注方向」区；预设聚焦美股大方向与 A股港股主力。</p>
            <div className="space-y-2 mb-3">
              {PRESET_DIRECTIONS.map((d) => (
                <label key={d.id} className="flex items-center gap-2 text-sm cursor-pointer">
                  <input type="checkbox" checked={!!presetOn[d.id]} onChange={(e) => setPresetOn({ ...presetOn, [d.id]: e.target.checked })} />
                  {d.name}
                  <span className="text-xs text-text-muted">（{d.words.length} 个关键词）</span>
                </label>
              ))}
            </div>
            <div className="text-xs text-text-secondary mb-1">自定义方向（输入关键词，空格/逗号分隔为多组）</div>
            <div className="flex flex-wrap gap-1.5 mb-2">
              {customDirs.map((c) => (
                <span key={c} className="inline-flex items-center gap-1 text-xs bg-bg-secondary border border-border rounded px-2 py-0.5">
                  {c}
                  <button className="text-danger" onClick={() => setCustomDirs(customDirs.filter((x) => x !== c))}>×</button>
                </span>
              ))}
            </div>
            <div className="flex gap-2 mb-4">
              <input value={dirInput} onChange={(e) => setDirInput(e.target.value)} placeholder="如：AI算力 新能源车 医药"
                className="flex-1 rounded border border-border px-3 py-1.5 text-sm outline-none focus:border-primary-500" />
              <Button variant="secondary" size="sm" onClick={() => {
                const v = dirInput.trim();
                if (v && !customDirs.includes(v)) { setCustomDirs([...customDirs, v]); setDirInput(''); }
              }}>添加</Button>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" size="sm" onClick={() => setDirOpen(false)}>取消</Button>
              <Button size="sm" onClick={() => {
                saveCustomDirs(customDirs);
                setDirOpen(false);
                void refresh();
              }}>保存方向并抓取</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
