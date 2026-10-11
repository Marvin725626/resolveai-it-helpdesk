import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Activity, ArrowDownToLine, ArrowRight, BookOpen, Check, ChevronRight, CircleHelp, Cpu, FileText, History, Layers, LogOut, MessageSquare, Plus, Send, ShieldCheck, Ticket, Wrench, Zap } from 'lucide-react';

type Evidence = { code: string; title: string; content: string; overlap: number; rrf_score: number };
type Tool = { name: string; arguments: Record<string, unknown>; result: Record<string, unknown>; duration_ms: number };
type Trace = { node: string; label: string; duration_ms: number; detail: Record<string, unknown> };
type Run = { run_id: string; question: string; status: string; answer?: string; answer_sources?: string[]; category?: string; evidence?: Evidence[]; tools?: Tool[]; trace?: Trace[]; ticket_id?: string; escalate?: boolean; reason?: string; latency_ms?: number; error?: string; supported?: boolean };
type TicketItem = { id: string; subject: string; status: string; priority: string; description: string; reason: string; created_at: string };
type Book = { id: string; code: string; title: string; content: string; keywords: string };
type Overview = { chunks: number; runs: number; open_tickets: number; mode: string; database: string; embedding_provider: string; services: { name: string; status: string; detail: string }[] };
type View = 'diagnose' | 'tickets' | 'knowledge' | 'history' | 'settings';
const nav = [{ id: 'diagnose', label: '智能诊断', icon: MessageSquare }, { id: 'tickets', label: '工单队列', icon: Ticket }, { id: 'knowledge', label: '知识库', icon: BookOpen }, { id: 'history', label: '运行记录', icon: History }, { id: 'settings', label: '运行配置', icon: Cpu }] as const;
const examples = [{ tag: 'VPN / 网络', text: 'VPN 连不上，提示认证超时，怎么排查？' }, { tag: '软件 / 安装', text: '如何安装公司批准的办公软件？' }, { tag: '账号 / 权限', text: '我需要 GitLab 管理员权限，帮我找人工处理' }];
const statusLabel: Record<string, string> = { OPEN: '待处理', ESCALATED: '转人工', IN_PROGRESS: '处理中', RESOLVED: '已解决', CLOSED: '已关闭', WAITING_FOR_CUSTOMER: '等待反馈' };
const toolLabel: Record<string, string> = { get_account_status: '账号状态', get_service_status: '服务健康', search_history_tickets: '历史工单' };
const categoryLabel: Record<string, string> = { vpn: 'VPN / 网络', account: '身份与权限', software: '办公软件', service: '内部服务', email: '企业邮箱', unknown: '未分类问题' };

function App() {
  const [token, setToken] = useState(localStorage.getItem('resolveai_token') || '');
  const [view, setView] = useState<View>('diagnose');
  const [overview, setOverview] = useState<Overview>();
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<Run>();
  const [trace, setTrace] = useState<Trace[]>([]);
  const [tickets, setTickets] = useState<TicketItem[]>([]);
  const [books, setBooks] = useState<Book[]>([]);
  const [history, setHistory] = useState<{ id: string; question: string; created_at: string; result: Run }[]>([]);
  const [showAdd, setShowAdd] = useState(false);
  const [loginBusy, setLoginBusy] = useState(false);
  const [email, setEmail] = useState('demo@resolveai.example.com');
  const [password, setPassword] = useState('ResolveAI123!');
  const abort = useRef<AbortController | undefined>(undefined);

  function logout() { abort.current?.abort(); localStorage.removeItem('resolveai_token'); setToken(''); setOverview(undefined); setResult(undefined); setTrace([]); }
  async function api<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch('/api/v1' + path, { ...init, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...init?.headers } });
    if (response.status === 401) logout();
    if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(typeof body.detail === 'string' ? body.detail : `请求失败 (${response.status})`); }
    return response.json();
  }
  async function refresh() {
    const [o, t, b, h] = await Promise.all([api<Overview>('/helpdesk/overview'), api<TicketItem[]>('/helpdesk/tickets'), api<Book[]>('/helpdesk/runbooks'), api<typeof history>('/helpdesk/runs')]);
    setOverview(o); setTickets(t); setBooks(b); setHistory(h);
  }
  useEffect(() => { if (token) refresh().catch(e => setError(e.message)); return () => abort.current?.abort(); }, [token]);

  async function login(event: FormEvent) {
    event.preventDefault(); setLoginBusy(true); setError('');
    try {
      const response = await fetch('/api/v1/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '登录失败，请检查邮箱与密码');
      localStorage.setItem('resolveai_token', body.access_token); setToken(body.access_token);
    } catch (e) { setError(e instanceof Error ? e.message : '连接失败'); }
    finally { setLoginBusy(false); }
  }

  async function diagnose(event: FormEvent) {
    event.preventDefault(); if (busy || question.trim().length < 4) return;
    setBusy(true); setError(''); setResult(undefined); setTrace([]);
    abort.current = new AbortController();
    try {
      const response = await fetch('/api/v1/helpdesk/runs/stream', { method: 'POST', signal: abort.current.signal,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ request_id: crypto.randomUUID(), question: question.trim() }) });
      if (response.status === 401) logout();
      if (!response.ok || !response.body) { const body = await response.json(); throw new Error(typeof body.detail === 'string' ? body.detail : '诊断请求失败'); }
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ''; let completed = false;
      const consume = (block: string) => {
        const data = block.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n');
        if (!data) return;
        const event = JSON.parse(data);
        if (event.type === 'trace') setTrace(current => [...current, event.step]);
        if (event.type === 'result' || event.type === 'error') { setResult(event.result); completed = true; if (event.result.error) setError(event.result.error); }
      };
      while (true) {
        const chunk = await reader.read(); buffer += decoder.decode(chunk.value, { stream: !chunk.done });
        let boundary: number;
        while ((boundary = buffer.indexOf('\n\n')) !== -1) { consume(buffer.slice(0, boundary)); buffer = buffer.slice(boundary + 2); }
        if (chunk.done) { if (buffer.trim()) consume(buffer); break; }
      }
      if (!completed) throw new Error('连接中断，未收到最终诊断。请重新提交。');
      await refresh();
    } catch (e) { if (!(e instanceof DOMException && e.name === 'AbortError')) setError(e instanceof Error ? e.message : '诊断失败'); }
    finally { setBusy(false); }
  }

  async function changeStatus(id: string, status: string) {
    try { setError(''); await api(`/helpdesk/tickets/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) }); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : '状态更新失败'); }
  }
  async function addBook(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    try { setError(''); await api('/helpdesk/runbooks', { method: 'POST', body: JSON.stringify(Object.fromEntries(form)) }); setShowAdd(false); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : '知识入库失败'); }
  }
  function exportRun() {
    if (!result) return; const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `resolveai-${result.run_id}.json`; anchor.click(); URL.revokeObjectURL(url);
  }
  const citedEvidence = (result?.evidence || []).filter(e => result?.answer_sources ? result.answer_sources.includes(e.code) : result?.answer?.includes(`[${e.code}]`));

  if (!token) return <main className="login-screen"><div className="login-story"><a className="brand" href="/"><span className="brand-mark"><Layers size={23}/></span>ResolveAI<span className="beta">IT</span></a><div className="login-copy"><span className="eyebrow light">YOUR IT SUPPORT, CONNECTED</span><h1>从问题描述，<br/>到有依据的解决方案。</h1><p>连接知识、诊断工具与人工支持。每一步有记录，每个回答有来源。</p><div className="login-flow"><span><BookOpen/>知识检索</span><ChevronRight/><span><Wrench/>只读诊断</span><ChevronRight/><span><Ticket/>工单流转</span></div></div><small>基于 AI SupportPro · MIT License · ResolveAI 扩展</small></div><div className="login-panel"><div className="login-form-wrap"><span className="eyebrow">SUPPORT WORKSPACE</span><h2>进入支持工作台</h2><p className="muted">演示工作区已配置 IT 知识库与模拟服务状态。</p><form onSubmit={login}><label>工作邮箱<input type="email" value={email} onChange={e => setEmail(e.target.value)} required autoComplete="username"/></label><label>密码<input type="password" value={password} onChange={e => setPassword(e.target.value)} required autoComplete="current-password"/></label>{error && <div className="error" role="alert">{error}</div>}<button className="primary login-button" disabled={loginBusy}>{loginBusy ? '正在连接…' : '进入工作台'}<ArrowRight size={18}/></button></form><div className="demo-note"><ShieldCheck size={19}/><div><strong>本地演示环境</strong><span>预填账号仅用于本地测试。账号及服务检查使用模拟数据。</span></div></div></div></div></main>;

  return <div className="shell"><a href="#main" className="skip-link">跳到主要内容</a><aside className="sidebar"><a className="brand" href="/"><span className="brand-mark"><Layers size={23}/></span>ResolveAI<span className="beta">IT</span></a><div className="workspace"><span className="workspace-icon">R</span><div><strong>IT 支持工作区</strong><small>本地演示环境</small></div></div><p className="nav-caption">工作台</p><nav aria-label="工作台导航">{nav.map(item => <button key={item.id} className={view === item.id ? 'nav-item active' : 'nav-item'} aria-current={view === item.id ? 'page' : undefined} onClick={() => { setView(item.id); setError(''); }}><item.icon size={19}/>{item.label}{item.id === 'tickets' && overview && overview.open_tickets > 0 && <span className="nav-count">{overview.open_tickets}</span>}</button>)}</nav><div className="sidebar-bottom"><div className="sidebar-note"><ShieldCheck size={18}/><span>回答附带知识来源<br/>高风险操作转人工处理</span></div><div className="profile"><span className="avatar">IT</span><div><strong>支持工程师</strong><small>演示账号</small></div><button className="icon-button" aria-label="退出登录" onClick={logout}><LogOut size={17}/></button></div></div></aside><div className="main-wrap"><header className="topbar"><div>工作台<ChevronRight size={14}/><strong>{nav.find(n => n.id === view)?.label}</strong></div><div className="topbar-right"><span className="mode-pill"><i/>{overview?.mode === 'openai' ? '模型已配置 · 工具模拟' : '离线演示模式'}</span><span className="topbar-date">IT SERVICE DESK</span></div></header><main id="main" className="main"><div className="page-heading"><div><span className="eyebrow">RESOLVE WITH EVIDENCE</span><h1>{view === 'diagnose' ? '让 IT 问题更快得到响应' : nav.find(n => n.id === view)?.label}</h1><p>{view === 'diagnose' ? '描述遇到的问题，查看诊断依据、执行过程与下一步。' : view === 'tickets' ? '保留完整诊断上下文，让人工支持从正确的位置接手。' : view === 'knowledge' ? '经过入库与检索的 SOP，是回答依据的起点。' : view === 'history' ? '回看每一次诊断的证据、工具结果与运行轨迹。' : '查看当前模型、检索与数据源的实际配置。'}</p></div><span className="heading-badge"><ShieldCheck size={16}/>可追踪的支持流程</span></div>{error && <div className="error" role="alert">{error}</div>}
    <div className="stats-row"><div><span><BookOpen size={17}/>知识片段</span><strong>{overview?.chunks ?? '—'}<small>已入库</small></strong></div><div><span><Activity size={17}/>诊断运行</span><strong>{overview?.runs ?? '—'}<small>实际记录</small></strong></div><div><span><Ticket size={17}/>待处理工单</span><strong>{overview?.open_tickets ?? '—'}<small>工作区内</small></strong></div><div><span><ShieldCheck size={17}/>工具数据</span><strong className="stat-text">模拟环境<small>只读检查</small></strong></div></div>
    {view === 'diagnose' && <div className="diagnose-layout"><div className="diagnose-column"><section className="panel composer"><div className="panel-title"><span className="title-icon"><Zap size={19}/></span><div><h2>今天有什么需要帮忙？</h2><p>VPN、账号权限、办公软件或内部服务</p></div></div><form onSubmit={diagnose}><label className="sr-only" htmlFor="question">描述 IT 问题</label><textarea id="question" value={question} onChange={e => setQuestion(e.target.value)} disabled={busy} maxLength={2000} placeholder="例如：VPN 连不上，提示认证超时，已经重启客户端…"/><div className="composer-footer"><span><ShieldCheck size={14}/>请勿输入密码、验证码或访问令牌</span><button className="primary" disabled={busy || question.trim().length < 4}>{busy ? '正在诊断…' : '开始诊断'}<Send size={16}/></button></div></form><div className="example-row">{examples.map(item => <button key={item.tag} disabled={busy} onClick={() => setQuestion(item.text)}><span>{item.tag}</span><ArrowRight size={14}/></button>)}</div></section>
      {(busy || trace.length > 0 || result) && <section className="panel trace-panel"><div className="section-heading"><h2><Activity size={18}/>执行轨迹</h2><span className={busy ? 'small-pill working' : 'small-pill'}>{busy ? '运行中' : `${result?.latency_ms ?? 0} ms`}</span></div><ol className="trace-list">{(result?.trace || trace).map((step, i) => <li key={`${step.node}-${i}`}><span className="step-check"><Check size={13}/></span><strong>{step.label}</strong><span>{step.duration_ms.toFixed(1)} ms</span><details><summary>详情</summary><pre>{JSON.stringify(step.detail, null, 2)}</pre></details></li>)}</ol>{busy && <div className="running"><span className="spinner"/>正在执行下一步检查…</div>}</section>}
      {result?.answer && <section className="panel answer-panel"><div className="section-heading"><h2><MessageSquare size={18}/>诊断结果</h2><button className="text-button" onClick={exportRun}><ArrowDownToLine size={15}/>导出记录</button></div><div className="answer-meta"><span className="small-pill">{categoryLabel[result.category || 'unknown']}</span><span className={result.escalate ? 'small-pill amber' : 'small-pill green'}>{result.escalate ? '需要人工协助' : '已给出排查建议'}</span></div><div className="answer-text">{result.answer}</div>{result.ticket_id && <div className="ticket-link"><Ticket size={20}/><div><strong>人工工单已创建</strong><small>{result.reason} · {result.ticket_id.slice(0, 8)}</small></div><button className="text-button" onClick={() => setView('tickets')}>查看工单<ArrowRight size={15}/></button></div>}</section>}
      {!busy && !result && <section className="empty-guidance"><div className="empty-symbol"><Layers size={28}/></div><h3>每一步，都有依据</h3><p>知识检索 → 证据检查 → 工具诊断 → 回答或人工工单</p><div><span><FileText size={16}/>查看引用</span><span><Wrench size={16}/>追踪工具</span><span><History size={16}/>回溯记录</span></div></section>}
    </div><aside className="context-column"><section className="panel service-panel"><div className="section-heading"><h2><Activity size={17}/>服务状态</h2><span className="micro-label">模拟数据</span></div>{overview?.services.map(service => <div className="service-row" key={service.name}><span className={service.status === 'operational' ? 'status-dot' : 'status-dot degraded'}/><strong>{service.name}</strong><span>{service.status === 'operational' ? '运行正常' : '服务降级'}</span></div>)}<p className="panel-footnote">工具从本地 fixture 读取状态，未连接真实企业系统。</p></section><section className="panel evidence-panel"><div className="section-heading"><h2><BookOpen size={17}/>引用证据</h2><span className="small-pill">{result?.supported ? citedEvidence.length : 0}</span></div>{result?.supported ? citedEvidence.map((e, i) => <article className="evidence" key={`${e.code}-${i}`}><span className="source-code">[{e.code}]</span><h3>{e.title}</h3><p>{e.content.slice(0, 110)}…</p><details><summary>查看原文<ChevronRight size={12}/></summary><p className="full-content">{e.content}</p><small>词项覆盖 {Math.round(e.overlap * 100)}% · RRF {e.rrf_score}</small></details></article>) : <div className="context-empty"><FileText size={24}/><p>完成诊断后，相关 SOP<br/>与来源会显示在这里。</p></div>}</section><section className="panel"><div className="section-heading"><h2><Wrench size={17}/>工具调用</h2></div>{result?.tools?.length ? result.tools.map((tool, i) => <details className="tool-detail" key={i}><summary><span>{toolLabel[tool.name] || tool.name}</span><span>{tool.duration_ms.toFixed(1)} ms</span></summary><pre>{JSON.stringify(tool.result, null, 2)}</pre></details>) : <p className="muted tiny">运行后展示实际返回结果。</p>}</section><div className="help-note"><CircleHelp size={18}/><p>证据不足时会再次检索；仍无法诊断则将上下文转交人工。</p></div></aside></div>}
    {view === 'tickets' && <section className="panel"><div className="section-heading"><h2>支持工单<span className="small-pill">{tickets.length}</span></h2><button className="text-button" onClick={() => refresh().catch(e => setError(e.message))}>刷新列表</button></div>{tickets.length === 0 ? <div className="context-empty large"><Ticket size={36}/><h3>当前没有工单</h3><p>需人工介入的诊断将自动出现在这里。</p></div> : <div className="ticket-list">{tickets.map(t => <article className="ticket-card" key={t.id}><div><span className="source-code">#{t.id.slice(0, 8)}</span><h3>{t.subject}</h3><p>{t.reason}</p><small>{new Date(t.created_at).toLocaleString('zh-CN', { timeZone: 'Asia/Hong_Kong' })} · {t.priority === 'HIGH' ? '高优先级' : '普通优先级'}</small></div><div className="ticket-actions"><span className={t.status === 'RESOLVED' || t.status === 'CLOSED' ? 'small-pill green' : 'small-pill amber'}>{statusLabel[t.status]}</span>{['OPEN','ESCALATED','CLOSED','RESOLVED','WAITING_FOR_CUSTOMER'].includes(t.status) && <button className="secondary" onClick={() => changeStatus(t.id,'IN_PROGRESS')}>{['CLOSED','RESOLVED'].includes(t.status) ? '重新处理' : '接手处理'}</button>}{t.status === 'IN_PROGRESS' && <button className="secondary" onClick={() => changeStatus(t.id,'RESOLVED')}>标记解决</button>}{t.status === 'RESOLVED' && <button className="secondary" onClick={() => changeStatus(t.id,'CLOSED')}>关闭工单</button>}</div><details className="ticket-context"><summary>诊断上下文</summary><pre>{t.description}</pre></details></article>)}</div>}</section>}
    {view === 'knowledge' && <section className="panel"><div className="section-heading"><h2>IT 操作手册与 FAQ</h2><button className="primary" onClick={() => setShowAdd(!showAdd)}><Plus size={16}/>{showAdd ? '收起表单' : '新增知识'}</button></div>{showAdd && <form className="knowledge-form" onSubmit={addBook}><label>来源代码<input name="code" placeholder="DNS-001" pattern="[A-Z]{2,10}-[0-9]{3,5}" required/></label><label>标题<input name="title" minLength={2} maxLength={200} placeholder="DNS 解析失败 SOP" required/></label><label className="wide">关键词<input name="keywords" placeholder="dns 网络 解析 故障" maxLength={500}/></label><label className="wide">操作步骤<textarea name="content" minLength={20} maxLength={15000} required placeholder="说明适用范围、检查步骤和人工升级条件（至少 20 字）"/></label><button className="primary">保存并建立检索索引<ArrowRight size={15}/></button></form>}<div className="book-grid">{books.map(book => <article className="book-card" key={book.id}><div className="book-icon"><BookOpen size={22}/></div><span className="source-code">{book.code}</span><h3>{book.title}</h3><p>{book.content.slice(0,100)}…</p><details><summary>查看全部内容</summary><p className="full-content">{book.content}</p></details></article>)}</div></section>}
    {view === 'history' && <section className="panel"><div className="section-heading"><h2>最近 30 次运行</h2><span className="micro-label">当前账号</span></div>{history.length === 0 ? <div className="context-empty large"><History size={35}/><h3>还没有运行记录</h3><p>从智能诊断提交一个问题开始。</p></div> : history.map(run => <button className="history-row" key={run.id} onClick={() => { setResult(run.result); setTrace(run.result.trace || []); setQuestion(run.question); setView('diagnose'); }}><span className="history-icon"><MessageSquare size={18}/></span><span><strong>{run.question}</strong><small>{new Date(run.created_at).toLocaleString('zh-CN', { timeZone: 'Asia/Hong_Kong' })} · {run.result.status === 'completed' ? '已完成' : run.result.status} · {run.result.latency_ms || 0} ms</small></span><ChevronRight size={17}/></button>)}</section>}
    {view === 'settings' && <section className="panel settings-panel"><h2>当前运行环境</h2><dl><div><dt>回答与工具选择</dt><dd>{overview?.mode === 'mock' ? '离线规则与 SOP 摘录' : 'OpenAI-compatible 模型'}</dd></div><div><dt>检索向量</dt><dd>{overview?.embedding_provider}</dd></div><div><dt>数据库</dt><dd>{overview?.database === 'sqlite' ? 'SQLite · 本地小规模回退' : 'PostgreSQL · pgvector'}</dd></div><div><dt>账号 / 服务工具</dt><dd>模拟 fixture · 只读</dd></div><div><dt>检索流程</dt><dd>稀疏 + 向量 → RRF → 词项覆盖重排</dd></div><div><dt>来源与许可证</dt><dd><a href="https://github.com/theclevertrader/ai-supportpro" target="_blank" rel="noreferrer">AI SupportPro · MIT</a></dd></div></dl><div className="config-note"><h3>切换真实模型</h3><p>在项目 <code>backend/.env</code> 中配置模型地址、名称和 API Key，重启后端。详细步骤见 README。若更换 embedding 模型或维度，需要重新建索引。</p><p>账户状态与服务检查尚未接入企业系统；当前版本用于流程演示和开发验证。</p></div></section>}
    <footer className="footer"><span>ResolveAI · IT HelpDesk Agent</span><span>基于 AI SupportPro / MIT · 已保留来源</span></footer></main></div></div>;
}
export default App;
