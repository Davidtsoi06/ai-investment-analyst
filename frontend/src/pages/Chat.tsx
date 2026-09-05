// S13 智能问答与研报解读：聊天界面（气泡/输入/快捷问题/加载态/规则模式徽章/对话历史）+ 研报解读（列表/搜索/解读展示）
// 契约：POST /api/chat/ask、GET /api/chat/history、GET /api/research/list、POST /api/research/interpret（后端契约见 t1）
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode, KeyboardEvent } from 'react';
import { Link } from 'react-router-dom';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import Loading from '../components/ui/Loading';
import {
  askChat,
  getAiStatus,
  getChatHistory,
  getResearchList,
  interpretResearch,
  parseApiError,
} from '../services/api';
import type { ChatHistoryItem, ResearchInterpret, ResearchItem } from '../services/api';

/** 兼容后端返回数组或 {items:[...]}/{list:[...]} 两种包装 */
function toList<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[];
  if (data && typeof data === 'object') {
    const d = data as Record<string, unknown>;
    if (Array.isArray(d.items)) return d.items as T[];
    if (Array.isArray(d.list)) return d.list as T[];
  }
  return [];
}

/** 消息模型 */
interface Msg {
  id: number;
  role: 'user' | 'assistant';
  text: string;
  category?: string;
  degraded?: boolean;
  error?: boolean;
}

const WELCOME: Msg = {
  id: 0,
  role: 'assistant',
  text: '你好，我是 AI 投资分析助手。\n\n我可以结合**实时行情**与**你的持仓**回答投资问题，例如：\n- 我的持仓有什么问题？\n- 600519 最近表现如何？\n- 对比一下中芯国际和台积电的估值\n- 半导体行业前景如何？\n\nAI 回答仅供参考，不构成投资建议。',
};

const QUICK_QUESTIONS = [
  '我的持仓有什么问题？',
  '600519 最近表现如何？',
  '对比一下中芯国际和台积电的估值',
  '半导体行业前景如何？',
];

/** 行内 **加粗** 渲染（不引入 markdown 库，仅文本节点安全） */
function inlineBold(text: string, key: string): ReactNode {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  if (parts.length === 1) return text;
  return parts.map((p, i) => (i % 2 === 1 ? <strong key={key + '-' + i} className="font-semibold text-text">{p}</strong> : p));
}

/** 轻量 Markdown 分段渲染：标题 / 列表 / 【标签】 / 段落，参考 Reports 页 renderSummary */
function renderRich(text: string, keyPrefix: string) {
  return text.split('\n').map((line, i) => {
    const t = line.trim();
    if (!t) return <div key={keyPrefix + '-e' + i} className="h-1.5" />;
    const h = /^(#{1,4})\s+(.*)$/.exec(t);
    if (h) {
      const lvl = h[1].length;
      const size = lvl <= 2 ? 'text-sm font-bold' : lvl === 3 ? 'text-sm font-semibold' : 'text-xs font-semibold';
      return (
        <p key={keyPrefix + '-h' + i} className={'text-primary-900 mt-1 ' + size}>
          {inlineBold(h[2], keyPrefix + '-hb' + i)}
        </p>
      );
    }
    const bullet = /^[-*•]\s+(.*)$/.exec(t) || /^\d+[.、]\s+(.*)$/.exec(t);
    if (bullet) {
      return (
        <p key={keyPrefix + '-b' + i} className="text-sm leading-6 text-text-secondary flex gap-1.5">
          <span className="text-primary-500 shrink-0">•</span>
          <span className="whitespace-pre-wrap">{inlineBold(bullet[1], keyPrefix + '-bi' + i)}</span>
        </p>
      );
    }
    if (t.startsWith('【')) {
      return (
        <p key={keyPrefix + '-tag' + i} className="text-sm leading-6 font-bold text-primary-700">
          {inlineBold(t, keyPrefix + '-tg' + i)}
        </p>
      );
    }
    return (
      <p key={keyPrefix + '-p' + i} className="text-sm leading-6 text-text-secondary whitespace-pre-wrap">
        {inlineBold(t, keyPrefix + '-pi' + i)}
      </p>
    );
  });
}

/** 评级 → 徽章配色：买入系绿 / 中性系黄 / 卖出系红 */
function ratingVariant(rating: string | null | undefined): 'success' | 'warning' | 'danger' | 'default' {
  const r = (rating || '').trim();
  if (/买入|增持|推荐|强烈|优于|跑赢|outperform|buy|overweight/i.test(r)) return 'success';
  if (/卖出|减持|回避|弱于|跑输|sell|underweight/i.test(r)) return 'danger';
  if (/中性|持有|观望|同步|hold|neutral/i.test(r)) return 'warning';
  return 'default';
}

/** 时间显示：截取 yyyy-mm-dd 部分 */
function fmtDate(s: string | null | undefined): string {
  if (!s) return '';
  const m = /(\d{4}-\d{2}-\d{2})/.exec(s);
  return m ? m[1] : s.slice(0, 10);
}

/** UTC ISO 时间 → 北京时间展示（对话历史 created_at 为 UTC，转 UTC+8；非 ISO 降级取日期） */
function fmtBjt(s: string | null | undefined): string {
  if (!s) return '';
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return fmtDate(s);
  const bjt = new Date(d.getTime() + 8 * 3600 * 1000);
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    bjt.getUTCFullYear() + '-' + pad(bjt.getUTCMonth() + 1) + '-' + pad(bjt.getUTCDate()) +
    ' ' + pad(bjt.getUTCHours()) + ':' + pad(bjt.getUTCMinutes())
  );
}

/** 解读结果渲染：优先整段 Markdown，否则结构化字段 */
function renderInterpret(data: ResearchInterpret, keyPrefix: string) {
  const md = data.interpretation || data.summary || data.answer || data.content || data.core_views || '';
  if (md.trim()) return renderRich(md, keyPrefix);
  const sections: { label: string; value?: string }[] = [
    { label: '目标价', value: data.target_price },
    { label: '评级变化', value: data.rating_change },
    { label: '关键假设', value: data.key_assumptions },
    { label: '风险提示', value: data.risks },
    { label: '持仓关联', value: data.holdings_relation },
  ];
  const has = sections.filter((s) => s.value && s.value.trim());
  if (has.length === 0) return <p className="text-sm text-text-secondary">暂无解读内容。</p>;
  return (
    <div className="space-y-3">
      {has.map((s) => (
        <div key={s.label}>
          <div className="text-xs font-bold text-primary-700 mb-1">【{s.label}】</div>
          <div className="text-sm text-text-secondary leading-6 whitespace-pre-wrap">{s.value}</div>
        </div>
      ))}
    </div>
  );
}

export default function Chat() {
  const [tab, setTab] = useState<'chat' | 'research'>('chat');

  // ---- 聊天 ----
  const [messages, setMessages] = useState<Msg[]>([WELCOME]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const idRef = useRef(1);
  const sendingRef = useRef(false);
  const listRef = useRef<HTMLDivElement>(null);
  const nextId = () => idRef.current++;

  // ---- AI 连接状态（V1.0.9：有 Key 时不显示任何"无 Key"提示） ----
  const [aiStatus, setAiStatus] = useState<{ configured: boolean; last_error?: string; last_error_at?: string } | null>(null);

  // ---- 对话历史 ----
  const [history, setHistory] = useState<ChatHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');

  // ---- 研报 ----
  const [researchItems, setResearchItems] = useState<ResearchItem[]>([]);
  const [researchKeyword, setResearchKeyword] = useState('');
  const [researchLoading, setResearchLoading] = useState(false);
  const [researchError, setResearchError] = useState('');
  const [selectedTitle, setSelectedTitle] = useState<string | null>(null);
  const [interpret, setInterpret] = useState<ResearchInterpret | null>(null);
  const [interpretLoading, setInterpretLoading] = useState(false);
  const [interpretError, setInterpretError] = useState('');
  const searchSeq = useRef(0);
  const interpretSeq = useRef(0);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError('');
    const r = await getChatHistory(30);
    setHistoryLoading(false);
    if (r.ok) setHistory(toList<ChatHistoryItem>(r.data));
    else setHistoryError('对话历史获取失败：' + parseApiError(r.error));
  }, []);

  useEffect(() => {
    loadHistory();
    getAiStatus().then((r) => {
      if (r.ok && r.data) setAiStatus(r.data as { configured: boolean; last_error?: string; last_error_at?: string });
    }).catch(() => {});
  }, [loadHistory]);

  const send = useCallback(
    async (question: string) => {
      const q = question.trim();
      if (!q || sendingRef.current) return;
      sendingRef.current = true;
      setSending(true);
      setMessages((prev) => [...prev, { id: nextId(), role: 'user', text: q }]);
      const r = await askChat(q);
      if (r.ok && r.data) {
        const d = r.data;
        setMessages((prev) => [
          ...prev,
          { id: nextId(), role: 'assistant', text: d.answer || '（无回答内容）', category: d.category, degraded: !!d.degraded },
        ]);
        void loadHistory();
      } else {
        setMessages((prev) => [
          ...prev,
          { id: nextId(), role: 'assistant', text: '回答失败：' + parseApiError(r.error, '后端不可用，请稍后重试。'), error: true },
        ]);
      }
      sendingRef.current = false;
      setSending(false);
    },
    [loadHistory],
  );

  // 新消息自动滚动到底部
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, sending]);

  const submit = () => {
    const q = input.trim();
    if (!q || sending) return;
    setInput('');
    void send(q);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const handleReask = (q: string) => {
    if (sending) return;
    setTab('chat');
    void send(q);
  };

  /** 查看历史对话：把该条 question + answer 完整载入聊天区（#9） */
  const handleViewHistory = (h: ChatHistoryItem) => {
    setTab('chat');
    setMessages([
      { id: nextId(), role: 'user', text: h.question },
      {
        id: nextId(),
        role: 'assistant',
        text: h.answer || '（该条无回答内容）',
        category: h.category ?? undefined,
        degraded: !!h.degraded,
      },
    ]);
  };

  // ---- 研报 ----
  const loadResearch = useCallback(async (keyword: string) => {
    const seq = ++searchSeq.current;
    setResearchLoading(true);
    setResearchError('');
    const r = await getResearchList(keyword, 10);
    if (seq !== searchSeq.current) return;
    setResearchLoading(false);
    if (r.ok) setResearchItems(toList<ResearchItem>(r.data));
    else setResearchError('研报列表获取失败：' + parseApiError(r.error));
  }, []);

  useEffect(() => {
    loadResearch('');
  }, [loadResearch]);

  const handleSearch = () => {
    const kw = researchKeyword.trim();
    setSelectedTitle(null);
    setInterpret(null);
    setInterpretError('');
    void loadResearch(kw);
  };

  const handleInterpret = async (item: ResearchItem) => {
    setSelectedTitle(item.title);
    setInterpret(null);
    setInterpretError('');
    setInterpretLoading(true);
    const seq = ++interpretSeq.current;
    const r = await interpretResearch(item.title);
    if (seq !== interpretSeq.current) return;
    setInterpretLoading(false);
    if (r.ok && r.data) setInterpret(r.data);
    else setInterpretError('解读失败：' + parseApiError(r.error));
  };

  const tabBtn = (key: 'chat' | 'research', label: string) => (
    <button
      type="button"
      onClick={() => setTab(key)}
      className={
        'px-4 py-1.5 text-sm transition-colors ' +
        (tab === key ? 'bg-primary-500 text-white' : 'text-text-secondary hover:bg-primary-50')
      }
    >
      {label}
    </button>
  );

  return (
    <div className="flex flex-col gap-4 h-[calc(100vh-3.5rem)] min-h-0">
      <div className="flex flex-wrap items-center justify-between gap-3 shrink-0">
        <div>
          <h1 className="text-xl font-bold text-primary-900">智能问答</h1>
          <p className="text-xs text-text-muted mt-1">
            结合实时行情与持仓上下文 · 个股分析 / 对比分析 / 持仓诊断 / 行业分析 / 策略咨询 / 数据查询 · 研报 AI 解读
          </p>
        </div>
        <div className="flex rounded-lg border border-border overflow-hidden bg-surface">
          {tabBtn('chat', '智能问答')}
          {tabBtn('research', '研报解读')}
        </div>
      </div>

      {/* AI 连接状态条：已配置不打扰；未配置才提示（V1.0.9） */}
      {aiStatus && !aiStatus.configured && (
        <div className="rounded border border-warning/40 bg-warning/5 px-3 py-1.5 shrink-0">
          <p className="text-xs text-warning">
            ⚠ 尚未检测到有效的 AI Key——回答将使用内置规则模式。请到{' '}
            <Link to="/settings" className="underline">系统设置 → DeepSeek AI 配置</Link> 填写并「保存并测试」。
            {aiStatus.last_error && <span className="text-text-muted">（最近错误：{aiStatus.last_error}）</span>}
          </p>
        </div>
      )}

      {tab === 'chat' ? (
        <div className="flex gap-4 items-stretch flex-1 min-h-0">
          {/* 聊天主区 */}
          <Card className="flex-1 flex flex-col p-0 overflow-hidden min-h-0">
            <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
              {messages.map((m) => (
                <div key={m.id} className={'flex ' + (m.role === 'user' ? 'justify-end' : 'justify-start')}>
                  <div
                    className={
                      'max-w-[80%] rounded-lg px-4 py-2.5 ' +
                      (m.role === 'user'
                        ? 'bg-primary-500 text-white rounded-tr-none'
                        : 'bg-surface border border-border rounded-tl-none')
                    }
                  >
                    {m.role === 'assistant' && (m.category || m.degraded || m.error) && (
                      <div className="flex flex-wrap gap-1.5 mb-1.5">
                        {m.category && <Badge variant="default">{m.category}</Badge>}
                        {m.degraded && <Badge variant="warning">规则模式</Badge>}
                        {m.error && <Badge variant="danger">失败</Badge>}
                      </div>
                    )}
                    <div className="text-sm leading-6 whitespace-pre-wrap">
                      {m.role === 'user' ? m.text : renderRich(m.text, 'm' + m.id)}
                    </div>
                  </div>
                </div>
              ))}
              {sending && (
                <div className="flex justify-start">
                  <div className="bg-surface border border-border rounded-lg rounded-tl-none px-4 py-3 flex items-center gap-1.5">
                    {[0, 1, 2].map((i) => (
                      <span
                        key={i}
                        className="w-1.5 h-1.5 rounded-full bg-primary-300 animate-bounce"
                        style={{ animationDelay: i * 0.15 + 's' }}
                      />
                    ))}
                    <span className="text-xs text-text-muted ml-1">AI 正在结合实时行情与您的持仓分析...</span>
                  </div>
                </div>
              )}
            </div>

            {/* 快捷问题 */}
            <div className="px-4 pt-3 border-t border-border">
              <div className="flex flex-wrap gap-2">
                {QUICK_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    type="button"
                    disabled={sending}
                    onClick={() => {
                      setInput('');
                      void send(q);
                    }}
                    className="text-xs text-primary-700 bg-primary-50 hover:bg-primary-100 border border-primary-100 rounded-full px-3 py-1.5 transition-colors disabled:opacity-50"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>

            {/* 输入区 */}
            <form
              className="p-4 pt-3 flex gap-2 items-end"
              onSubmit={(e) => {
                e.preventDefault();
                submit();
              }}
            >
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={2}
                placeholder="输入问题，Enter 发送，Shift+Enter 换行（如：600519 最近表现如何？）"
                className="flex-1 rounded border border-border px-3 py-2 text-sm resize-none outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
              />
              <Button type="submit" disabled={sending || !input.trim()}>
                {sending ? '发送中...' : '发送'}
              </Button>
            </form>
          </Card>

          {/* 对话历史 */}
          <Card className="w-72 shrink-0 flex flex-col p-0 overflow-hidden min-h-0">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <h2 className="font-bold text-sm">对话历史</h2>
              <span className="text-xs text-text-muted">最近 30 条</span>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto">
              {historyError && <p className="px-4 py-2 text-xs text-danger">{historyError}</p>}
              {historyLoading && history.length === 0 && <Loading className="py-4" text="加载中..." />}
              {!historyLoading && history.length === 0 && !historyError && (
                <p className="px-4 py-3 text-xs text-text-muted">暂无历史记录，提问后自动保存。</p>
              )}
              {history.map((h) => (
                <div
                  key={h.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => handleViewHistory(h)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleViewHistory(h); }}
                  className="w-full text-left px-4 py-2.5 border-b border-border last:border-b-0 hover:bg-primary-50/60 transition-colors cursor-pointer"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-text truncate flex-1">{h.question}</span>
                    {!!h.degraded && <Badge variant="warning">规则</Badge>}
                  </div>
                  <div className="flex items-center gap-2 mt-1 text-xs text-text-muted">
                    {h.category && <span>{h.category}</span>}
                    {h.created_at && <span className="font-number">{fmtBjt(h.created_at)}</span>}
                  </div>
                  <div className="mt-1.5 flex items-center gap-3 text-xs">
                    <span className="text-primary-600">👁 查看完整对话</span>
                    <button
                      type="button"
                      disabled={sending}
                      onClick={(e) => { e.stopPropagation(); handleReask(h.question); }}
                      className="text-text-muted hover:text-primary-600 disabled:opacity-50"
                    >
                      ↻ 重新提问
                    </button>
                  </div>
                </div>
              ))}
            </div>
            <div className="px-4 py-2.5 border-t border-border">
              <Button variant="secondary" size="sm" onClick={() => void loadHistory()} disabled={historyLoading}>
                {historyLoading ? '刷新中...' : '刷新'}
              </Button>
            </div>
          </Card>
        </div>
      ) : (
        <div className="flex gap-4 items-stretch flex-1 min-h-0">
          {/* 研报列表 */}
          <Card className="w-[46%] shrink-0 flex flex-col p-0 overflow-hidden min-h-0">
            <div className="px-4 py-3 border-b border-border shrink-0">
              <h2 className="font-bold text-sm mb-2">研报列表</h2>
              <div className="flex gap-2">
                <input
                  value={researchKeyword}
                  onChange={(e) => setResearchKeyword(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleSearch();
                  }}
                  placeholder="搜索研报（股票/关键词）"
                  className="flex-1 rounded border border-border px-3 py-1.5 text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                />
                <Button size="sm" onClick={handleSearch} disabled={researchLoading}>
                  {researchLoading ? '搜索中...' : '搜索'}
                </Button>
              </div>
              <p className="text-xs text-text-muted mt-2">东方财富研报 · 数据源不可用时自动降级为资讯匹配</p>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto">
              {researchError && <p className="px-4 py-3 text-xs text-danger">{researchError}</p>}
              {researchLoading && researchItems.length === 0 && <Loading className="py-4" text="加载中..." />}
              {!researchLoading && researchItems.length === 0 && !researchError && (
                <p className="px-4 py-3 text-xs text-text-muted">暂无研报数据，可点击「搜索」重试。</p>
              )}
              {researchItems.map((item) => (
                <button
                  key={item.title}
                  type="button"
                  onClick={() => void handleInterpret(item)}
                  className={
                    'w-full text-left px-4 py-3 border-b border-border last:border-b-0 transition-colors ' +
                    (selectedTitle === item.title ? 'bg-primary-50' : 'hover:bg-primary-50/60')
                  }
                >
                  <div className="text-sm font-medium text-text leading-5">{item.title}</div>
                  <div className="flex flex-wrap items-center gap-2 mt-1.5 text-xs text-text-secondary">
                    {item.org && <span className="text-primary-700">{item.org}</span>}
                    {item.rating && <Badge variant={ratingVariant(item.rating)}>{item.rating}</Badge>}
                    {item.rating_change && <span className="text-text-muted">评级变化 {item.rating_change}</span>}
                    {item.date && <span className="text-text-muted font-number">{fmtDate(item.date)}</span>}
                    {item.source === 'news_cache' && <Badge variant="warning">资讯源</Badge>}
                    {item.target_price !== null && item.target_price !== undefined && item.target_price !== '' && (
                      <span className="text-text-muted">目标价 {String(item.target_price)}</span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          </Card>

          {/* 解读结果 */}
          <Card className="flex-1 flex flex-col p-0 overflow-hidden min-h-0">
            <div className="px-4 py-3 border-b border-border flex flex-wrap items-center gap-2 shrink-0">
              <h2 className="font-bold text-sm">AI 解读</h2>
              {interpret?.holding_match && <Badge variant="success">关联持仓</Badge>}
              {interpret?.degraded && <Badge variant="warning">规则模式</Badge>}
              {selectedTitle && <span className="text-xs text-text-muted truncate max-w-[60%]">{selectedTitle}</span>}
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto p-4">
              {interpretLoading && <p className="text-sm text-text-muted">正在解读研报（AI 提取核心观点，无 Key 时降级为原文展示）...</p>}
              {interpretError && <p className="text-sm text-danger">{interpretError}</p>}
              {!interpretLoading && !interpretError && !interpret && (
                <div className="text-sm text-text-muted space-y-2">
                  <p>点击左侧研报条目，AI 将提取：</p>
                  <ul className="list-disc pl-5 space-y-1">
                    <li>核心观点（约 300 字摘要）</li>
                    <li>目标价与评级变化</li>
                    <li>关键假设与风险提示</li>
                    <li>与你的持仓关联分析</li>
                  </ul>
                </div>
              )}
              {interpret && !interpretLoading && !interpretError && (
                <div className="border-l-2 border-primary-100 pl-3">{renderInterpret(interpret, 'itp')}</div>
              )}
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}