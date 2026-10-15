import { useEffect, useRef, useState } from "react";
import { Bell, Check, RefreshCw } from "lucide-react";

type Api = <T>(path: string, init?: RequestInit) => Promise<T>;
type Notification = {
  id: string;
  ticket_id: string;
  kind: string;
  title: string;
  text: string;
  created_at: string;
  read_at: string | null;
};
export type NotificationPage = {
  items: Notification[];
  unread_count: number;
  has_more: boolean;
  next_before: number | null;
};
export default function NotificationsPanel({
  api,
  onCount,
  onOpenTicket,
}: {
  api: Api;
  onCount: (count: number) => void;
  onOpenTicket: (id: string) => void;
}) {
  const [data, setData] = useState<NotificationPage>();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const apiRef = useRef(api);
  apiRef.current = api;
  const countRef = useRef(onCount);
  countRef.current = onCount;
  useEffect(() => {
    const current = ++generation.current;
    setLoading(true);
    setError("");
    setData(undefined);
    apiRef
      .current<NotificationPage>(
        `/helpdesk/notifications?unread_only=${unreadOnly}`,
      )
      .then((page) => {
        if (current === generation.current) {
          setData(page);
          countRef.current(page.unread_count);
        }
      })
      .catch((e) => {
        if (current === generation.current) setError(e.message);
      })
      .finally(() => {
        if (current === generation.current) setLoading(false);
      });
    return () => {
      generation.current++;
    };
  }, [unreadOnly, revision]);
  async function markRead(id?: string, ticketId?: string) {
    if (busy || loading) return;
    const current = generation.current;
    setBusy(true);
    setError("");
    try {
      await api(`/helpdesk/notifications/${id ? `${id}/read` : "read-all"}`, {
        method: "POST",
      });
      if (current !== generation.current) return;
      const page = await api<NotificationPage>(
        `/helpdesk/notifications?unread_only=${unreadOnly}`,
      );
      if (current !== generation.current) return;
      setData(page);
      onCount(page.unread_count);
      if (ticketId) onOpenTicket(ticketId);
    } catch (e) {
      if (current === generation.current)
        setError(e instanceof Error ? e.message : "更新通知失败");
    } finally {
      setBusy(false);
    }
  }
  async function loadMore() {
    if (!data?.has_more || loading || busy) return;
    const current = generation.current;
    setLoading(true);
    setError("");
    try {
      const page = await api<NotificationPage>(
        `/helpdesk/notifications?unread_only=${unreadOnly}&before=${data.next_before}`,
      );
      if (current !== generation.current) return;
      setData(
        (old) =>
          old && {
            ...page,
            items: [
              ...old.items,
              ...page.items.filter(
                (item) => !old.items.some((seen) => seen.id === item.id),
              ),
            ],
          },
      );
      onCount(page.unread_count);
    } catch (e) {
      if (current === generation.current)
        setError(e instanceof Error ? e.message : "读取通知失败");
    } finally {
      if (current === generation.current) setLoading(false);
    }
  }
  return (
    <section className="panel notifications-panel" aria-label="个人通知中心">
      <div className="section-heading">
        <h2>
          <Bell size={20} /> 我的通知{" "}
          <span className="small-pill">{data?.unread_count ?? "—"} 条未读</span>
        </h2>
        <div className="notification-tools">
          <button
            className="secondary"
            disabled={loading || busy}
            onClick={() => setRevision((v) => v + 1)}
          >
            <RefreshCw size={15} />
            刷新
          </button>
          <button
            className="secondary"
            disabled={loading || busy || !data?.unread_count}
            onClick={() => markRead()}
          >
            <Check size={15} />
            全部已读
          </button>
        </div>
      </div>
      <p className="panel-footnote">
        工单分派、交接和状态变化会出现在这里。打开工单时将这条通知标为已读。
      </p>
      <div className="notification-tools" aria-label="通知筛选">
        <button
          className={unreadOnly ? "secondary" : "primary"}
          aria-pressed={!unreadOnly}
          disabled={busy || loading}
          onClick={() => setUnreadOnly(false)}
        >
          全部
        </button>
        <button
          className={unreadOnly ? "primary" : "secondary"}
          aria-pressed={unreadOnly}
          disabled={busy || loading}
          onClick={() => setUnreadOnly(true)}
        >
          未读
        </button>
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {loading && (
        <p className="panel-footnote" role="status">
          正在读取通知…
        </p>
      )}
      {data && !data.items.length && (
        <div className="context-empty large">
          <Bell size={36} />
          <h3>{unreadOnly ? "没有未读通知" : "暂无通知"}</h3>
          <p>新的工单交接提醒会保存在这里。</p>
        </div>
      )}
      <ul className="notification-list">
        {data?.items.map((item) => (
          <li
            className={
              item.read_at ? "notification-item" : "notification-item unread"
            }
            key={item.id}
          >
            <div className="notification-content">
              <div className="notification-title">
                <strong>{item.title}</strong>
                <span className="small-pill">
                  {item.read_at ? "已读" : "未读"}
                </span>
              </div>
              <p>{item.text}</p>
              <small className="muted">
                {new Date(item.created_at).toLocaleString("zh-CN", {
                  timeZone: "Asia/Hong_Kong",
                })}{" "}
                · #{item.ticket_id.slice(0, 8)}
              </small>
            </div>
            <div className="notification-tools">
              <button
                className="secondary"
                disabled={busy || loading}
                onClick={() => markRead(item.id, item.ticket_id)}
              >
                打开工单
              </button>
              {!item.read_at && (
                <button
                  className="text-button"
                  disabled={busy || loading}
                  onClick={() => markRead(item.id)}
                >
                  标为已读
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
      {data?.has_more && (
        <button
          className="secondary"
          disabled={loading || busy}
          onClick={loadMore}
        >
          加载更早通知
        </button>
      )}
    </section>
  );
}
