import { useEffect, useRef, useState, type FormEvent } from "react";
import { Bookmark, RefreshCw } from "lucide-react";
type Api = <T>(path: string, init?: RequestInit) => Promise<T>;
export type QueueFilters = {
  q: string;
  status: string | null;
  priority: string | null;
  assignment: "all" | "mine" | "unassigned";
  sla: "on_track" | "due_soon" | "overdue" | null;
  page_size: number;
};
type View = {
  id: string;
  name: string;
  filters: QueueFilters;
  version: number;
};
export default function SavedQueueViews({
  api,
  filters,
  disabled = false,
  onApply,
}: {
  api: Api;
  filters: QueueFilters;
  disabled?: boolean;
  onApply: (filters: QueueFilters) => void;
}) {
  const [items, setItems] = useState<View[]>([]),
    [selected, setSelected] = useState(""),
    [name, setName] = useState(""),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [retryCreate, setRetryCreate] = useState(false),
    [retryDelete, setRetryDelete] = useState(false);
  const generation = useRef(0);
  const pendingCreate = useRef<{ key: string; body: string } | undefined>(
      undefined,
    ),
    pendingDelete = useRef<{ id: string; version: number } | undefined>(
      undefined,
    );
  async function load() {
    const current = generation.current;
    const result = await api<{ items: View[] }>("/helpdesk/queue-views");
    if (generation.current === current) setItems(result.items);
    return result.items;
  }
  useEffect(() => {
    const current = ++generation.current;
    load()
      .catch((e) => generation.current === current && setError(e.message))
      .finally(() => generation.current === current && setLoading(false));
    return () => {
      generation.current++;
    };
  }, []);
  const chosen = items.find((item) => item.id === selected);
  async function save(event: FormEvent, update = false) {
    event.preventDefault();
    if (busy || disabled || !name.trim() || (update && !chosen)) return;
    const current = generation.current;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      let path = "/helpdesk/queue-views",
        method = "POST",
        body: string;
      if (update && chosen) {
        path += `/${chosen.id}`;
        method = "PUT";
        body = JSON.stringify({
          expected_version: chosen.version,
          name: name.trim(),
          filters,
        });
      } else {
        const key = JSON.stringify([name.trim(), filters]);
        if (!pendingCreate.current || pendingCreate.current.key !== key)
          pendingCreate.current = {
            key,
            body: JSON.stringify({
              request_id: crypto.randomUUID(),
              name: name.trim(),
              filters,
            }),
          };
        setRetryCreate(true);
        body = pendingCreate.current.body;
      }
      const saved = await api<{ view: View }>(path, { method, body });
      if (generation.current !== current) return;
      pendingCreate.current = undefined;
      setRetryCreate(false);
      setSelected(saved.view.id);
      setItems((old) => [
        ...old.filter((item) => item.id !== saved.view.id),
        saved.view,
      ]);
      setNotice(update ? "所选视图已更新。" : "个人筛选视图已保存。");
      await load();
    } catch (e) {
      if (generation.current !== current) return;
      const status = (e as Error & { status?: number }).status;
      setError(
        e instanceof Error ? e.message : "保存结果未确认，可以重试原请求。",
      );
      if (status && status < 500) {
        pendingCreate.current = undefined;
        setRetryCreate(false);
      }
      if (status === 409) {
        try {
          await load();
          setNotice("列表已刷新，请核对视图后再操作。");
        } catch {
          setNotice("列表刷新失败，请手动刷新后再试。");
        }
      }
    } finally {
      if (generation.current === current) setBusy(false);
    }
  }
  async function remove() {
    if (!chosen || busy || disabled) return;
    const current = generation.current;
    const request =
      pendingDelete.current?.id === chosen.id
        ? pendingDelete.current
        : { id: chosen.id, version: chosen.version };
    pendingDelete.current = request;
    setRetryDelete(true);
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(`/helpdesk/queue-views/${request.id}`, {
        method: "DELETE",
        body: JSON.stringify({ expected_version: request.version }),
      });
      if (generation.current !== current) return;
      pendingDelete.current = undefined;
      setRetryDelete(false);
      setSelected("");
      setName("");
      setItems((old) => old.filter((item) => item.id !== request.id));
      setNotice("筛选视图已删除。");
      await load();
    } catch (e) {
      if (generation.current !== current) return;
      const status = (e as Error & { status?: number }).status;
      setError(e instanceof Error ? e.message : "删除结果未确认，可重试删除。");
      if (status && status < 500) {
        pendingDelete.current = undefined;
        setRetryDelete(false);
      }
      if (status === 409) {
        try {
          await load();
          setNotice("列表已刷新，请核对当前版本。");
        } catch {
          setNotice("列表刷新失败，请稍后重试。");
        }
      }
    } finally {
      if (generation.current === current) setBusy(false);
    }
  }
  return (
    <section className="saved-queue-views" aria-label="个人筛选视图">
      <div className="section-heading">
        <h3>
          <Bookmark size={16} />
          个人筛选视图 <span className="small-pill">{items.length} / 10</span>
        </h3>
        <button
          className="text-button"
          disabled={busy || disabled}
          onClick={() => {
            setError("");
            setLoading(true);
            load()
              .catch((e) => setError(e.message))
              .finally(() => setLoading(false));
          }}
        >
          <RefreshCw size={14} />
          刷新视图
        </button>
      </div>
      <p className="panel-footnote">
        仅自己可见，保存当前搜索、筛选和每页数量；应用后回到第 1
        页并收起通知直达工单。
      </p>
      {loading && (
        <p role="status" className="panel-footnote">
          正在读取个人视图…
        </p>
      )}
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <p role="status" className="panel-footnote">
          {notice}
        </p>
      )}
      <div className="saved-view-actions">
        <label htmlFor="saved-view-select">
          已保存视图
          <select
            id="saved-view-select"
            value={selected}
            disabled={busy || disabled || loading}
            onChange={(e) => {
              setSelected(e.target.value);
              const next = items.find((item) => item.id === e.target.value);
              setName(next?.name || "");
              pendingCreate.current = undefined;
              pendingDelete.current = undefined;
              setRetryCreate(false);
              setRetryDelete(false);
            }}
          >
            <option value="">选择个人视图</option>
            {items.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <button
          className="secondary"
          disabled={!chosen || busy || disabled}
          onClick={() => chosen && onApply(chosen.filters)}
        >
          应用视图
        </button>
        <button
          className="text-button"
          disabled={!chosen || busy || disabled}
          onClick={remove}
        >
          {retryDelete ? "重试删除视图" : "删除所选视图"}
        </button>
      </div>
      <form className="saved-view-actions" onSubmit={(event) => save(event)}>
        <label htmlFor="saved-view-name">
          视图名称
          <input
            id="saved-view-name"
            value={name}
            maxLength={50}
            disabled={busy || disabled}
            onChange={(e) => {
              setName(e.target.value);
              pendingCreate.current = undefined;
              setRetryCreate(false);
            }}
            placeholder="例如：我负责的紧急工单"
          />
        </label>
        <button
          className="secondary"
          disabled={
            busy ||
            disabled ||
            loading ||
            !name.trim() ||
            (!retryCreate && items.length >= 10)
          }
        >
          {busy ? "正在保存…" : retryCreate ? "重试原保存" : "保存为新视图"}
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy || disabled || !chosen || !name.trim()}
          onClick={(event) => save(event as unknown as FormEvent, true)}
        >
          更新所选视图
        </button>
      </form>
    </section>
  );
}
