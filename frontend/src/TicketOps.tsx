import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Clock, History, MessageSquare, Send, UserRound } from 'lucide-react';

export type TicketSummary = {
  id: string; subject: string; status: string; priority: string; description: string; reason: string;
  created_at: string; updated_at: string; resolved_at?: string; assigned_agent_name?: string;
  assigned_agent_id?: string; sla: { state: string; due_at: string; target_hours: number; remaining_minutes: number };
};
type Event = { id: string; type: string; author: string; created_at: string; payload: { text?: string; from?: string; to?: string; reason?: string; agent_name?: string } };
type Detail = { ticket: TicketSummary; event_count: number; events: Event[] };
type Api = <T>(path: string, init?: RequestInit) => Promise<T>;
const status: Record<string, string> = { OPEN: '待处理', ESCALATED: '转人工', IN_PROGRESS: '处理中', RESOLVED: '已解决', CLOSED: '已关闭', WAITING_FOR_CUSTOMER: '等待反馈' };
export const slaLabel: Record<string, string> = { on_track: '目标时间内', due_soon: '即将超时', overdue: '已超时', met: '按时完成', breached: '超时完成', completed_unknown: '已完成 · 时间未知' };
const time = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Hong_Kong' });
export function SlaBadge({ ticket }: { ticket: TicketSummary }) {
  return <span className={`sla-badge ${ticket.sla.state}`} title={`演示解决目标 ${ticket.sla.target_hours} 小时，截止 ${time(ticket.sla.due_at)}`}><Clock size={13}/>{slaLabel[ticket.sla.state] || ticket.sla.state}</span>;
}
function eventTitle(event: Event) {
  if (event.type === 'created') return '诊断流程自动转人工';
  if (event.type === 'assigned') return `工单接手：${event.payload.agent_name}`;
  if (event.type === 'status_changed') return `${status[event.payload.from || ''] || event.payload.from} → ${status[event.payload.to || ''] || event.payload.to}`;
  return event.type === 'note' ? '处理备注' : event.type;
}

export default function TicketOps({ ticket, api, onChanged }: { ticket: TicketSummary; api: Api; onChanged: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<Detail>();
  const [revision, setRevision] = useState(0);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef<{ text: string; identity: string } | undefined>(undefined);
  useEffect(() => {
    if (!open) return;
    let active = true;
    setDetail(undefined); setError('');
    api<Detail>(`/helpdesk/tickets/${ticket.id}`).then(value => { if (active) setDetail(value); }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [open, ticket.id, ticket.updated_at, revision]);
  async function addNote(event: FormEvent) {
    event.preventDefault(); if (busy || draft.trim().length < 2) return;
    setBusy(true); setError('');
    const text = draft.trim();
    if (pending.current?.text !== text) pending.current = { text, identity: crypto.randomUUID() };
    try {
      await api(`/helpdesk/tickets/${ticket.id}/notes`, { method: 'POST', body: JSON.stringify({ request_id: pending.current.identity, note: text }) });
      pending.current = undefined; setDraft(''); setRevision(value => value + 1); await onChanged();
    } catch (e) { setError(e instanceof Error ? e.message : '备注保存失败'); }
    finally { setBusy(false); }
  }
  return <details className="ticket-context ticket-ops" onToggle={event => setOpen(event.currentTarget.open)}><summary><History size={15}/>处理记录与诊断上下文</summary>{open && <div className="ticket-ops-body">
    {error && <div className="error" role="alert">{error}</div>}
    {!detail && !error && <p className="muted" role="status">正在读取处理记录…</p>}
    {detail && <><div className="ticket-operation-meta"><div><UserRound size={16}/><span>接手人<strong>{detail.ticket.assigned_agent_name || '尚未接手'}</strong></span></div><div><Clock size={16}/><span>演示解决目标<strong>{detail.ticket.sla.target_hours} 小时 · {slaLabel[detail.ticket.sla.state]}</strong><small>截止 {time(detail.ticket.sla.due_at)}</small></span></div></div><p className="panel-footnote">按自然小时计时，等待反馈不暂停；这是一组开发演示目标，不是企业服务承诺。</p>
    <div className="section-heading"><h3>处理记录</h3><span className="micro-label">最近 {detail.events.length} / {detail.event_count} 条</span></div>
    <ol className="ticket-timeline">{detail.events.map(event => <li key={event.id}><span className={`timeline-marker ${event.type === 'note' ? 'note-marker' : ''}`}>{event.type === 'note' ? <MessageSquare size={13}/> : <History size={13}/>}</span><div><strong>{eventTitle(event)}</strong><small>{event.author} · {time(event.created_at)}</small>{event.payload.text && <p>{event.payload.text}</p>}{event.type === 'created' && <p>{event.payload.reason}</p>}</div></li>)}</ol>{!detail.events.length && <p className="panel-footnote">这是升级前的工单；新操作会开始记录，不补造历史记录。</p>}
    <form className="note-form" onSubmit={addNote}><label htmlFor={`note-${ticket.id}`}>新增内部处理备注<textarea id={`note-${ticket.id}`} value={draft} onChange={event => setDraft(event.target.value)} minLength={2} maxLength={3000} disabled={busy} placeholder="记录已检查的项目、处理结果或需要员工补充的信息…"/></label><div><small>仅工作区支持人员可见。请勿填写密码或令牌。</small><button className="secondary" disabled={busy || draft.trim().length < 2}>{busy ? '正在保存…' : '保存备注'}<Send size={14}/></button></div></form>
    <details className="diagnostic-payload"><summary>查看原始诊断上下文</summary><pre>{detail.ticket.description}</pre></details></>}
  </div>}</details>;
}
