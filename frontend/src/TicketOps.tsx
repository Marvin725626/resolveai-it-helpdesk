import { useEffect, useRef, useState, type FormEvent } from "react";
import { Clock, History, MessageSquare, Send, UserRound } from "lucide-react";

export type TicketSummary = {
  id: string;
  subject: string;
  status: string;
  priority: string;
  description?: string;
  reason: string;
  created_at: string;
  updated_at: string;
  resolved_at?: string;
  assigned_agent_name?: string;
  assigned_agent_id?: string;
  sla: {
    state: string;
    due_at: string;
    target_hours: number;
    remaining_minutes: number;
  };
};
type Event = {
  id: string;
  type: string;
  author: string;
  created_at: string;
  payload: {
    text?: string;
    from?: string;
    to?: string;
    reason?: string;
    agent_name?: string;
    from_agent_name?: string;
  };
};
type Detail = {
  ticket: TicketSummary;
  event_count: number;
  events: Event[];
  has_more: boolean;
  next_before: number | null;
  can_manage_assignment: boolean;
};
type EventPage = {
  events: Event[];
  has_more: boolean;
  next_before: number | null;
};
type Roster = {
  items: { id: string; name: string; role: string }[];
  total: number;
  truncated: boolean;
};
type Api = <T>(path: string, init?: RequestInit) => Promise<T>;
type FrozenAssignment = {
  body: string;
  requestId: string;
  target: string | null;
  reason: string;
  ticketId: string;
};
const status: Record<string, string> = {
  OPEN: "待处理",
  ESCALATED: "转人工",
  IN_PROGRESS: "处理中",
  RESOLVED: "已解决",
  CLOSED: "已关闭",
  WAITING_FOR_CUSTOMER: "等待反馈",
};
export const slaLabel: Record<string, string> = {
  on_track: "目标时间内",
  due_soon: "即将超时",
  overdue: "已超时",
  met: "按时完成",
  breached: "超时完成",
  completed_unknown: "已完成 · 时间未知",
};
const time = (value: string) =>
  new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Hong_Kong" });
export function SlaBadge({ ticket }: { ticket: TicketSummary }) {
  return (
    <span
      className={`sla-badge ${ticket.sla.state}`}
      title={`演示解决目标 ${ticket.sla.target_hours} 小时，截止 ${time(ticket.sla.due_at)}`}
    >
      <Clock size={13} />
      {slaLabel[ticket.sla.state] || ticket.sla.state}
    </span>
  );
}
function eventTitle(event: Event) {
  if (event.type === "created") return "诊断流程自动转人工";
  if (event.type === "assigned") return `工单接手：${event.payload.agent_name}`;
  if (event.type === "assignment_changed")
    return `接手人变更：${event.payload.from_agent_name || "未分派"} → ${event.payload.agent_name || "释放工单"}`;
  if (event.type === "status_changed")
    return `${status[event.payload.from || ""] || event.payload.from} → ${status[event.payload.to || ""] || event.payload.to}`;
  return event.type === "note" ? "处理备注" : event.type;
}
const activeStatus = (value: string) => !["RESOLVED", "CLOSED"].includes(value);

export default function TicketOps({
  ticket,
  api,
  onChanged,
}: {
  ticket: TicketSummary;
  api: Api;
  onChanged: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<Detail>();
  const [revision, setRevision] = useState(0);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [assignmentTarget, setAssignmentTarget] = useState("");
  const [selectedAssignee, setSelectedAssignee] = useState<{
    id: string;
    name: string;
    role: string;
  }>();
  const [assignmentReason, setAssignmentReason] = useState("");
  const [rosterQuery, setRosterQuery] = useState("");
  const [roster, setRoster] = useState<Roster>();
  const [rosterLoading, setRosterLoading] = useState(false);
  const [assignmentMessage, setAssignmentMessage] = useState("");
  const [pendingAssignment, setPendingAssignment] =
    useState<FrozenAssignment>();
  const [staleAssignment, setStaleAssignment] = useState(false);
  const [olderLoading, setOlderLoading] = useState(false);
  const [olderError, setOlderError] = useState("");
  const generation = useRef(0);
  const rosterGeneration = useRef(0);
  const pendingNote = useRef<{ text: string; identity: string } | undefined>(
    undefined,
  );

  useEffect(() => {
    if (!open) {
      generation.current += 1;
      return;
    }
    const current = ++generation.current;
    setDetail(undefined);
    setError("");
    setOlderError("");
    setOlderLoading(false);
    setRoster(undefined);
    setRosterQuery("");
    setStaleAssignment(false);
    if (pendingAssignment?.ticketId === ticket.id) {
      setAssignmentTarget(pendingAssignment.target || "");
      setSelectedAssignee(undefined);
      setAssignmentReason(pendingAssignment.reason);
    } else {
      setAssignmentTarget(ticket.assigned_agent_id || "");
      setSelectedAssignee(
        ticket.assigned_agent_id
          ? {
              id: ticket.assigned_agent_id,
              name: ticket.assigned_agent_name || "当前接手人",
              role: "",
            }
          : undefined,
      );
      setAssignmentReason("");
      if (pendingAssignment) setPendingAssignment(undefined);
    }
    api<Detail>(`/helpdesk/tickets/${ticket.id}`)
      .then((value) => {
        if (generation.current === current) setDetail(value);
      })
      .catch((e) => {
        if (generation.current === current) setError(e.message);
      });
    return () => {
      if (generation.current === current) generation.current += 1;
    };
  }, [open, ticket.id, ticket.updated_at, revision]);

  useEffect(() => {
    if (
      !open ||
      !detail?.can_manage_assignment ||
      !activeStatus(detail.ticket.status)
    )
      return;
    const current = ++rosterGeneration.current;
    const timer = window.setTimeout(() => {
      setRosterLoading(true);
      api<Roster>(`/helpdesk/assignees?q=${encodeURIComponent(rosterQuery)}`)
        .then((value) => {
          if (rosterGeneration.current === current) {
            setRoster(value);
            setSelectedAssignee(
              (previous) =>
                value.items.find((person) => person.id === assignmentTarget) ||
                previous,
            );
          }
        })
        .catch((e) => {
          if (rosterGeneration.current === current) setError(e.message);
        })
        .finally(() => {
          if (rosterGeneration.current === current) setRosterLoading(false);
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      if (rosterGeneration.current === current) rosterGeneration.current += 1;
    };
  }, [open, detail?.can_manage_assignment, detail?.ticket.status, rosterQuery]);

  async function addNote(event: FormEvent) {
    event.preventDefault();
    if (busy || draft.trim().length < 2) return;
    setBusy(true);
    setError("");
    const text = draft.trim();
    if (pendingNote.current?.text !== text)
      pendingNote.current = { text, identity: crypto.randomUUID() };
    try {
      await api(`/helpdesk/tickets/${ticket.id}/notes`, {
        method: "POST",
        body: JSON.stringify({
          request_id: pendingNote.current.identity,
          note: text,
        }),
      });
      pendingNote.current = undefined;
      setDraft("");
      setRevision((value) => value + 1);
      try {
        await onChanged();
      } catch (e) {
        setError(
          `备注已保存，但列表刷新失败：${e instanceof Error ? e.message : "请稍后刷新"}`,
        );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "备注保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function submitAssignment(event: FormEvent, retry = false) {
    event.preventDefault();
    if (
      busy ||
      !detail ||
      !detail.can_manage_assignment ||
      (!retry && !activeStatus(detail.ticket.status))
    )
      return;
    const target = assignmentTarget || null;
    const reason = assignmentReason.trim();
    if (!retry && reason.length < 2) {
      setError("请填写至少两个字符的交接原因");
      return;
    }
    if (!retry && target === (detail.ticket.assigned_agent_id || null)) {
      setError("接手人没有变化，请选择其他成员或释放工单");
      return;
    }
    let frozen = pendingAssignment;
    if (retry && frozen?.ticketId === ticket.id) {
      // Replay the exact original bytes, even if the ticket has since changed.
    } else {
      const requestId = crypto.randomUUID();
      const body = JSON.stringify({
        request_id: requestId,
        agent_id: target,
        reason,
        expected_updated_at: detail.ticket.updated_at,
      });
      frozen = { body, requestId, target, reason, ticketId: ticket.id };
      setPendingAssignment(frozen);
    }
    setBusy(true);
    setError("");
    setAssignmentMessage("");
    setStaleAssignment(false);
    try {
      await api(`/helpdesk/tickets/${ticket.id}/assignment`, {
        method: "POST",
        body: frozen.body,
      });
      setPendingAssignment(undefined);
      let refreshError = "";
      try {
        await onChanged();
      } catch (e) {
        refreshError = e instanceof Error ? e.message : "请刷新列表";
      }
      setRevision((value) => value + 1);
      if (refreshError)
        setAssignmentMessage(`交接已保存，列表刷新失败：${refreshError}`);
    } catch (e) {
      const statusCode = (e as Error & { status?: number }).status;
      setError(e instanceof Error ? e.message : "交接失败");
      if (statusCode === 409) {
        setPendingAssignment(undefined);
        setStaleAssignment(true);
        setAssignmentMessage(
          "工单已更新。请刷新后确认当前接手人，再重新提交。",
        );
      } else {
        setAssignmentMessage(
          "如果请求已送达，可用同一请求安全重试；修改选择或原因会创建新请求。",
        );
      }
    } finally {
      setBusy(false);
    }
  }

  async function refreshAfterConflict() {
    const current = ++generation.current;
    setOlderLoading(false);
    setOlderError("");
    setBusy(true);
    setError("");
    try {
      const fresh = await api<Detail>(`/helpdesk/tickets/${ticket.id}`);
      if (generation.current !== current) return;
      setDetail(fresh);
      setAssignmentTarget(fresh.ticket.assigned_agent_id || "");
      setSelectedAssignee(
        fresh.ticket.assigned_agent_id
          ? {
              id: fresh.ticket.assigned_agent_id,
              name: fresh.ticket.assigned_agent_name || "当前接手人",
              role: "",
            }
          : undefined,
      );
      setPendingAssignment(undefined);
      setStaleAssignment(false);
      setAssignmentMessage(
        "工单已刷新。确认接手人后，重新提交会使用新的工单版本。",
      );
    } catch (e) {
      if (generation.current === current)
        setError(e instanceof Error ? e.message : "刷新工单失败");
    } finally {
      setBusy(false);
    }
  }

  async function loadOlder() {
    if (!detail?.has_more || detail.next_before == null || olderLoading) return;
    const current = generation.current;
    setOlderLoading(true);
    setOlderError("");
    try {
      const page = await api<EventPage>(
        `/helpdesk/tickets/${ticket.id}/events?before=${detail.next_before}&page_size=50`,
      );
      if (generation.current !== current) return;
      setDetail((previous) => {
        if (!previous || previous.next_before !== detail.next_before)
          return previous;
        const seen = new Set(previous.events.map((item) => item.id));
        return {
          ...previous,
          events: [
            ...page.events.filter((item) => !seen.has(item.id)),
            ...previous.events,
          ],
          has_more: page.has_more,
          next_before: page.next_before,
        };
      });
    } catch (e) {
      if (generation.current === current)
        setOlderError(e instanceof Error ? e.message : "较早记录读取失败");
    } finally {
      if (generation.current === current) setOlderLoading(false);
    }
  }

  return (
    <details
      className="ticket-context ticket-ops"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <History size={15} />
        处理记录与诊断上下文
      </summary>
      {open && (
        <div className="ticket-ops-body">
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          {!detail && !error && (
            <p className="muted" role="status">
              正在读取处理记录…
            </p>
          )}
          {detail && (
            <>
              <div className="ticket-operation-meta">
                <div>
                  <UserRound size={16} />
                  <span>
                    接手人
                    <strong>
                      {detail.ticket.assigned_agent_name || "尚未接手"}
                    </strong>
                  </span>
                </div>
                <div>
                  <Clock size={16} />
                  <span>
                    演示解决目标
                    <strong>
                      {detail.ticket.sla.target_hours} 小时 ·{" "}
                      {slaLabel[detail.ticket.sla.state]}
                    </strong>
                    <small>截止 {time(detail.ticket.sla.due_at)}</small>
                  </span>
                </div>
              </div>
              <p className="panel-footnote">
                按自然小时计时，等待反馈不暂停；这是一组开发演示目标，不是企业服务承诺。
              </p>
              {detail.can_manage_assignment &&
                (activeStatus(detail.ticket.status) ||
                  pendingAssignment?.ticketId === ticket.id) && (
                  <form
                    className="note-form assignment-form"
                    onSubmit={(event) => submitAssignment(event)}
                  >
                    {activeStatus(detail.ticket.status) && (
                      <>
                        <label htmlFor={`assignee-search-${ticket.id}`}>
                          搜索工作区支持成员
                          <input
                            id={`assignee-search-${ticket.id}`}
                            value={rosterQuery}
                            onChange={(event) =>
                              setRosterQuery(event.target.value)
                            }
                            maxLength={100}
                            placeholder="输入姓名"
                            disabled={busy}
                          />
                        </label>
                        <label htmlFor={`assignee-${ticket.id}`}>
                          分派给
                          <select
                            id={`assignee-${ticket.id}`}
                            value={assignmentTarget}
                            onChange={(event) => {
                              setAssignmentTarget(event.target.value);
                              setPendingAssignment(undefined);
                            }}
                            disabled={busy || rosterLoading || !roster}
                          >
                            <option value="">释放工单（不指定接手人）</option>
                            {assignmentTarget &&
                              !(roster?.items || []).some(
                                (person) => person.id === assignmentTarget,
                              ) && (
                                <option value={assignmentTarget}>
                                  {selectedAssignee?.id === assignmentTarget
                                    ? selectedAssignee.name
                                    : detail.ticket.assigned_agent_id ===
                                        assignmentTarget
                                      ? detail.ticket.assigned_agent_name ||
                                        "当前接手人"
                                      : "已选成员"}
                                </option>
                              )}
                            {(roster?.items || []).map((person) => (
                              <option value={person.id} key={person.id}>
                                {person.name} ·{" "}
                                {person.role === "SUPPORT_AGENT"
                                  ? "支持人员"
                                  : "管理员"}
                              </option>
                            ))}
                          </select>
                        </label>
                        {rosterLoading && (
                          <small role="status">正在读取成员…</small>
                        )}
                        {roster?.truncated && (
                          <small>
                            匹配 {roster.total} 人，列表最多显示 50
                            人；请继续缩小搜索范围。
                          </small>
                        )}
                        <label htmlFor={`assignment-reason-${ticket.id}`}>
                          交接原因
                          <textarea
                            id={`assignment-reason-${ticket.id}`}
                            value={assignmentReason}
                            onChange={(event) => {
                              setAssignmentReason(event.target.value);
                              setPendingAssignment(undefined);
                            }}
                            minLength={2}
                            maxLength={1000}
                            disabled={busy}
                            placeholder="说明为何转交或释放工单…"
                          />
                        </label>
                        <div>
                          <small>变更接手人不会改变工单状态或演示时限。</small>
                          <button
                            className="secondary"
                            disabled={
                              busy ||
                              rosterLoading ||
                              !roster ||
                              assignmentReason.trim().length < 2 ||
                              assignmentTarget ===
                                (detail.ticket.assigned_agent_id || "")
                            }
                          >
                            {busy ? "正在保存…" : "保存交接"}
                            <Send size={14} />
                          </button>
                        </div>
                      </>
                    )}
                    {assignmentMessage && (
                      <p role="status" className="panel-footnote">
                        {assignmentMessage}
                      </p>
                    )}
                    {pendingAssignment?.ticketId === ticket.id &&
                      !staleAssignment && (
                        <button
                          type="button"
                          className="secondary"
                          disabled={busy}
                          onClick={(event) =>
                            submitAssignment(
                              event as unknown as FormEvent,
                              true,
                            )
                          }
                        >
                          重试原请求
                        </button>
                      )}
                    {staleAssignment && (
                      <button
                        type="button"
                        className="secondary"
                        disabled={busy}
                        onClick={refreshAfterConflict}
                      >
                        刷新工单
                      </button>
                    )}
                  </form>
                )}
              <div className="section-heading">
                <h3>处理记录</h3>
                <span className="micro-label">
                  已加载 {detail.events.length} / {detail.event_count} 条
                </span>
              </div>
              <ol className="ticket-timeline">
                {detail.events.map((event) => (
                  <li key={event.id}>
                    <span
                      className={`timeline-marker ${event.type === "note" ? "note-marker" : ""}`}
                    >
                      {event.type === "note" ? (
                        <MessageSquare size={13} />
                      ) : (
                        <History size={13} />
                      )}
                    </span>
                    <div>
                      <strong>{eventTitle(event)}</strong>
                      <small>
                        {event.author} · {time(event.created_at)}
                      </small>
                      {event.payload.reason && <p>{event.payload.reason}</p>}
                      {event.payload.text && <p>{event.payload.text}</p>}
                    </div>
                  </li>
                ))}
              </ol>
              {detail.has_more && (
                <div className="older-events">
                  {olderError && (
                    <div className="error" role="alert">
                      {olderError}
                    </div>
                  )}
                  <button
                    type="button"
                    className="secondary"
                    onClick={loadOlder}
                    disabled={olderLoading}
                  >
                    {olderLoading ? "正在读取较早记录…" : "加载较早记录"}
                  </button>
                </div>
              )}
              {!detail.events.length && (
                <p className="panel-footnote">
                  这是升级前的工单；新操作会开始记录，不补造历史记录。
                </p>
              )}
              <form className="note-form" onSubmit={addNote}>
                <label htmlFor={`note-${ticket.id}`}>
                  新增内部处理备注
                  <textarea
                    id={`note-${ticket.id}`}
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    minLength={2}
                    maxLength={3000}
                    disabled={busy}
                    placeholder="记录已检查的项目、处理结果或需要员工补充的信息…"
                  />
                </label>
                <div>
                  <small>仅工作区支持人员可见。请勿填写密码或令牌。</small>
                  <button
                    className="secondary"
                    disabled={busy || draft.trim().length < 2}
                  >
                    {busy ? "正在保存…" : "保存备注"}
                    <Send size={14} />
                  </button>
                </div>
              </form>
              <details className="diagnostic-payload">
                <summary>查看原始诊断上下文</summary>
                <pre>{detail.ticket.description}</pre>
              </details>
            </>
          )}
        </div>
      )}
    </details>
  );
}
