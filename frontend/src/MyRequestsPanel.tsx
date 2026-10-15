import { RequesterResolution } from "./TicketResolution";
import TicketAttachments from "./TicketAttachments";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowLeft, MessageSquare, Send, TicketCheck } from "lucide-react";

type Api = <T>(path: string, init?: RequestInit) => Promise<T>;
type Item = {
  id: string;
  subject: string;
  status: string;
  priority: string;
  assignee: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  source: string;
};
type Detail = {
  ticket: Item;
  timeline: {
    type: string;
    status?: string;
    author?: string;
    created_at: string;
  }[];
};
type Reply = {
  id: string;
  author_name: string;
  direction: "requester" | "support";
  body: string;
  created_at: string;
};
const labels: Record<string, string> = {
  OPEN: "待处理",
  ESCALATED: "转人工",
  IN_PROGRESS: "处理中",
  WAITING_FOR_CUSTOMER: "等待补充",
  RESOLVED: "已解决",
  CLOSED: "已关闭",
  created: "工单已创建",
  assigned: "支持人员已接手",
  assignment_changed: "工单交接更新",
  status_changed: "状态更新",
};
const time = (value: string) =>
  new Date(value).toLocaleString("zh-HK", { timeZone: "Asia/Hong_Kong" });

export default function MyRequestsPanel({
  api,
  initialTicketId,
  navigationKey,
}: {
  api: Api;
  initialTicketId?: string;
  navigationKey?: number;
}) {
  const [items, setItems] = useState<Item[]>([]);
  const [listPage, setListPage] = useState(1);
  const [listTotal, setListTotal] = useState(0);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Detail>();
  const [replies, setReplies] = useState<Reply[]>([]);
  const [replyBefore, setReplyBefore] = useState<number | null>(null);
  const [replyHasMore, setReplyHasMore] = useState(false);
  const [draft, setDraft] = useState("");
  const [explanation, setExplanation] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const generation = useRef(0);
  const lastNavigationKey = useRef<number | undefined>(undefined);
  const pending = useRef<
    { key: string; body: string; path: string } | undefined
  >(undefined);
  useEffect(() => {
    let active = true;
    if (
      initialTicketId &&
      navigationKey !== undefined &&
      lastNavigationKey.current !== navigationKey
    ) {
      lastNavigationKey.current = navigationKey;
      setSelected(initialTicketId);
    }
    api<{ items: Item[]; total: number }>(
      `/helpdesk/my-tickets?page=${listPage}&page_size=20`,
    )
      .then((page) => {
        if (!active) return;
        setItems(page.items);
        setListTotal(page.total);
        setSelected((current) => current || page.items[0]?.id || "");
      })
      .catch((e) => active && setError(e.message));
    return () => {
      active = false;
    };
  }, [navigationKey, listPage]);
  useEffect(() => {
    setDraft("");
    setExplanation("");
    pending.current = undefined;
    if (!selected) {
      setDetail(undefined);
      setReplies([]);
      return;
    }
    const current = ++generation.current;
    setLoading(true);
    setError("");
    setNotice("");
    setDetail(undefined);
    setReplies([]);
    Promise.all([
      api<Detail>(`/helpdesk/my-tickets/${selected}`),
      api<{ items: Reply[]; has_more: boolean; next_before: number | null }>(
        `/helpdesk/my-tickets/${selected}/replies?page_size=20`,
      ),
    ])
      .then(([fresh, thread]) => {
        if (generation.current !== current) return;
        setDetail(fresh);
        setReplies(thread.items);
        setReplyBefore(thread.next_before);
        setReplyHasMore(thread.has_more);
      })
      .catch((e) => {
        if (generation.current === current) setError(e.message);
      })
      .finally(() => {
        if (generation.current === current) setLoading(false);
      });
    return () => {
      if (generation.current === current) generation.current += 1;
    };
  }, [selected]);
  async function refresh() {
    const current = generation.current;
    const [fresh, thread, list] = await Promise.all([
      api<Detail>(`/helpdesk/my-tickets/${selected}`),
      api<{ items: Reply[]; has_more: boolean; next_before: number | null }>(
        `/helpdesk/my-tickets/${selected}/replies?page_size=20`,
      ),
      api<{ items: Item[]; total: number }>(
        `/helpdesk/my-tickets?page=${listPage}&page_size=20`,
      ),
    ]);
    if (generation.current !== current) return;
    setDetail(fresh);
    setReplies(thread.items);
    setReplyBefore(thread.next_before);
    setReplyHasMore(thread.has_more);
    setItems(list.items);
    setListTotal(list.total);
  }
  async function loadOlderReplies() {
    if (!selected || replyBefore === null || busy) return;
    const current = generation.current;
    const cursor = replyBefore;
    setBusy(true);
    setError("");
    try {
      const page = await api<{
        items: Reply[];
        has_more: boolean;
        next_before: number | null;
      }>(
        `/helpdesk/my-tickets/${selected}/replies?before=${cursor}&page_size=20`,
      );
      if (generation.current !== current) return;
      setReplies((previous) => [...page.items, ...previous]);
      setReplyBefore(page.next_before);
      setReplyHasMore(page.has_more);
    } catch (e) {
      if (generation.current === current)
        setError(e instanceof Error ? e.message : "读取较早回复失败");
    } finally {
      setBusy(false);
    }
  }
  async function sendReply(event: FormEvent) {
    event.preventDefault();
    if (!detail || busy || draft.trim().length < 2) return;
    const bodyText = draft.trim();
    const key = `reply:${selected}:${bodyText}`;
    if (!pending.current || pending.current.key !== key)
      pending.current = {
        key,
        path: `/helpdesk/my-tickets/${selected}/replies`,
        body: JSON.stringify({
          request_id: crypto.randomUUID(),
          expected_updated_at: detail.ticket.updated_at,
          body: bodyText,
        }),
      };
    setBusy(true);
    setError("");
    setNotice("");
    const current = generation.current;
    try {
      await api(pending.current.path, {
        method: "POST",
        body: pending.current.body,
      });
      if (generation.current !== current) return;
      pending.current = undefined;
      setDraft("");
      await refresh();
      if (generation.current === current) setNotice("补充资料已发送。");
    } catch (e) {
      if (generation.current !== current) return;
      setError(e instanceof Error ? e.message : "发送失败");
      if ((e as Error & { status?: number }).status === 409) {
        pending.current = undefined;
        try {
          await refresh();
          setNotice("工单已刷新，请核对状态后重新发送补充。");
        } catch {
          setNotice("工单版本冲突，刷新失败；请重新打开工单后再试。");
        }
      }
    } finally {
      setBusy(false);
    }
  }
  async function action(kind: "confirm-resolved" | "reopen") {
    if (!detail || busy || (kind === "reopen" && explanation.trim().length < 2))
      return;
    const text = explanation.trim();
    const key = `${kind}:${selected}:${text}`;
    if (!pending.current || pending.current.key !== key)
      pending.current = {
        key,
        path: `/helpdesk/my-tickets/${selected}/${kind}`,
        body: JSON.stringify({
          request_id: crypto.randomUUID(),
          expected_updated_at: detail.ticket.updated_at,
          ...(kind === "reopen" ? { explanation: text } : {}),
        }),
      };
    setBusy(true);
    setError("");
    setNotice("");
    const current = generation.current;
    try {
      await api(pending.current.path, {
        method: "POST",
        body: pending.current.body,
      });
      if (generation.current !== current) return;
      pending.current = undefined;
      setExplanation("");
      await refresh();
      if (generation.current === current)
        setNotice(
          kind === "reopen"
            ? "已告知支持人员问题仍未解决。"
            : "已确认解决并关闭工单。",
        );
    } catch (e) {
      if (generation.current !== current) return;
      setError(e instanceof Error ? e.message : "操作失败");
      if ((e as Error & { status?: number }).status === 409) {
        pending.current = undefined;
        try {
          await refresh();
          setNotice("工单已刷新，请核对最新状态后重新操作。");
        } catch {
          setNotice("工单版本冲突，刷新失败；请重新打开工单后再试。");
        }
      }
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel my-requests">
      <div className="my-requests-list">
        <h2>我的报障</h2>
        {items.length === 0 ? (
          <p className="muted">你还没有 AI 转人工的工单。</p>
        ) : (
          items.map((item) => (
            <button
              type="button"
              key={item.id}
              disabled={busy}
              className={
                selected === item.id ? "request-item active" : "request-item"
              }
              onClick={() => setSelected(item.id)}
            >
              <strong>{item.subject}</strong>
              <span>
                {labels[item.status] || item.status} · {item.priority}
              </span>
              <small>AI 转人工 · {time(item.created_at)}</small>
            </button>
          ))
        )}
        {listTotal > 20 && (
          <div className="request-pagination">
            <button
              className="secondary"
              disabled={busy || listPage <= 1}
              onClick={() => setListPage((value) => value - 1)}
            >
              上一页
            </button>
            <span>
              {listPage} / {Math.ceil(listTotal / 20)}
            </span>
            <button
              className="secondary"
              disabled={busy || listPage >= Math.ceil(listTotal / 20)}
              onClick={() => setListPage((value) => value + 1)}
            >
              下一页
            </button>
          </div>
        )}
      </div>
      <div className="my-request-detail">
        {loading && <p role="status">正在载入工单…</p>}
        {!selected && !loading && <p className="muted">从左侧选择一张工单。</p>}
        {detail && (
          <>
            <div className="request-toolbar">
              <button
                className="text-button mobile-request-back"
                disabled={busy}
                onClick={() => setSelected("")}
              >
                <ArrowLeft size={15} />
                返回工单列表
              </button>
              <button
                className="secondary"
                disabled={busy || loading}
                onClick={async () => {
                  setBusy(true);
                  setError("");
                  try {
                    await refresh();
                    setNotice("工单进度已刷新。");
                  } catch (e) {
                    setError(e instanceof Error ? e.message : "刷新失败");
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                刷新进度
              </button>
            </div>
            <div className="request-title">
              <TicketCheck size={20} />
              <div>
                <h2>{detail.ticket.subject}</h2>
                <p>
                  来源：AI 转人工 · 状态：
                  {labels[detail.ticket.status] || detail.ticket.status} ·
                  接手人：{detail.ticket.assignee || "待分派"}
                </p>
              </div>
            </div>
            <h3>处理进度</h3>
            <ol className="request-timeline">
              {detail.timeline.map((row, i) => (
                <li key={`${row.created_at}-${i}`}>
                  <span>
                    {labels[row.type] || row.type}
                    {row.status ? ` · ${labels[row.status] || row.status}` : ""}
                  </span>
                  <time>{time(row.created_at)}</time>
                </li>
              ))}
            </ol>
            <RequesterResolution
              api={api}
              ticketId={detail.ticket.id}
              updatedAt={detail.ticket.updated_at}
              status={detail.ticket.status}
              disabled={busy}
              onBusyChange={setBusy}
              onChanged={refresh}
            />
            <TicketAttachments
              key={detail.ticket.id}
              api={api}
              ticketId={detail.ticket.id}
              updatedAt={detail.ticket.updated_at}
              scope="my-tickets"
              disabled={busy}
              onBusyChange={setBusy}
              onChanged={refresh}
            />
            <h3>
              <MessageSquare size={16} /> 公开沟通
            </h3>
            <div className="request-replies">
              {replies.length === 0 ? (
                <p className="muted">支持人员接手后可在这里与你沟通。</p>
              ) : (
                replies.map((reply) => (
                  <article
                    className={`request-reply ${reply.direction}`}
                    key={reply.id}
                  >
                    <strong>
                      {reply.direction === "support"
                        ? `${reply.author_name} · 支持人员`
                        : "你"}
                    </strong>
                    <p>{reply.body}</p>
                    <time>{time(reply.created_at)}</time>
                  </article>
                ))
              )}
            </div>
            {replyHasMore && (
              <button
                className="secondary"
                disabled={busy}
                onClick={loadOlderReplies}
              >
                加载更早回复
              </button>
            )}
            {detail.ticket.status !== "CLOSED" && (
              <form className="request-reply-form" onSubmit={sendReply}>
                <label htmlFor="request-reply">补充资料</label>
                <textarea
                  id="request-reply"
                  maxLength={3000}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder="补充有助于处理问题的信息…"
                />
                <button
                  className="primary"
                  disabled={busy || draft.trim().length < 2}
                >
                  <Send size={15} />
                  {busy ? "发送中…" : "发送补充"}
                </button>
              </form>
            )}
            {detail.ticket.status === "RESOLVED" && (
              <div className="request-actions">
                <button
                  className="primary"
                  disabled={busy}
                  onClick={() => action("confirm-resolved")}
                >
                  确认解决并关闭
                </button>
                <label htmlFor="request-reopen">仍未解决时说明原因</label>
                <textarea
                  id="request-reopen"
                  maxLength={1000}
                  value={explanation}
                  onChange={(e) => setExplanation(e.target.value)}
                  placeholder="请说明仍未解决的情况…"
                />
                <button
                  className="secondary"
                  disabled={busy || explanation.trim().length < 2}
                  onClick={() => action("reopen")}
                >
                  仍未解决，重新处理
                </button>
              </div>
            )}
          </>
        )}
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <p className="success" role="status">
          {notice}
        </p>
      )}
    </section>
  );
}
