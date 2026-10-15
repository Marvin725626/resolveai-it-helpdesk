import { useEffect, useRef, useState, type FormEvent } from "react";
import { Download, Paperclip, Trash2, Upload } from "lucide-react";

type Api = <T>(
  path: string,
  init?: RequestInit & { responseType?: "blob" },
) => Promise<T>;
type Attachment = {
  id: string;
  filename: string;
  size_bytes: number;
  uploader_name: string;
  created_at: string;
  can_delete: boolean;
};
type Page = {
  items: Attachment[];
  can_upload: boolean;
  has_more: boolean;
  next_before: number | null;
  updated_at: string;
};
type FrozenUpload = { file: File; requestId: string; expected: string };
export default function TicketAttachments({
  api,
  ticketId,
  updatedAt,
  scope,
  disabled = false,
  onBusyChange,
  onChanged,
}: {
  api: Api;
  ticketId: string;
  updatedAt: string;
  scope: "my-tickets" | "tickets";
  disabled?: boolean;
  onBusyChange: (value: boolean) => void;
  onChanged: () => Promise<void>;
}) {
  const [data, setData] = useState<Page>();
  const [file, setFile] = useState<File>();
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const [pendingCleanup, setPendingCleanup] = useState<string>();
  const [hasPendingUpload, setHasPendingUpload] = useState(false);
  const pending = useRef<FrozenUpload | undefined>(undefined);
  const generation = useRef(0);
  const input = useRef<HTMLInputElement>(null);
  const path = `/helpdesk/${scope}/${ticketId}/attachments`;
  useEffect(() => {
    generation.current++;
    setFile(undefined);
    pending.current = undefined;
    setHasPendingUpload(false);
    setData(undefined);
    setError("");
    setNotice("");
    setPendingCleanup(undefined);
    return () => {
      generation.current++;
    };
  }, [ticketId, scope]);
  useEffect(() => {
    let active = true;
    setLoading(true);
    api<Page>(path)
      .then((page) => {
        if (active) setData(page);
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [path, updatedAt, revision]);
  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file || busy || disabled) return;
    if (file.size > 5 * 1024 * 1024) {
      setError("单个附件不能超过 5 MiB");
      return;
    }
    const current = generation.current;
    if (!pending.current)
      pending.current = {
        file,
        requestId: crypto.randomUUID(),
        expected: updatedAt,
      };
    const frozen = pending.current;
    setHasPendingUpload(true);
    setBusy(true);
    onBusyChange(true);
    setError("");
    setNotice("");
    try {
      const body = new FormData();
      body.set("file", frozen.file);
      body.set("request_id", frozen.requestId);
      body.set("expected_updated_at", frozen.expected);
      await api(path, { method: "POST", body });
      if (generation.current !== current) return;
      // Clear the request as soon as the server confirms success, even if a later refresh fails.
      pending.current = undefined;
      setHasPendingUpload(false);
      setFile(undefined);
      if (input.current) input.current.value = "";
      setNotice("附件已上传。");
      setRevision((v) => v + 1);
      await onChanged();
    } catch (e) {
      if (generation.current !== current) return;
      const status = (e as Error & { status?: number }).status;
      if (status && status < 500) {
        pending.current = undefined;
        setHasPendingUpload(false);
      }
      setError(e instanceof Error ? e.message : "上传失败；可以重试原请求。");
      if (status === 409) {
        try {
          await onChanged();
          setRevision((v) => v + 1);
          setNotice("工单已刷新，请核对后重新上传。");
        } catch {
          setNotice("请先刷新工单，再重新上传。");
        }
      }
    } finally {
      if (generation.current === current) setBusy(false);
      onBusyChange(false);
    }
  }
  async function download(item: Attachment) {
    if (busy || disabled) return;
    const current = generation.current;
    setBusy(true);
    onBusyChange(true);
    setError("");
    try {
      const blob = await api<Blob>(`${path}/${item.id}/download`, {
        responseType: "blob",
      });
      if (generation.current !== current) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = item.filename;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      if (generation.current === current)
        setError(e instanceof Error ? e.message : "下载失败");
    } finally {
      if (generation.current === current) setBusy(false);
      onBusyChange(false);
    }
  }
  async function remove(id: string) {
    if (busy || disabled) return;
    const current = generation.current;
    setBusy(true);
    onBusyChange(true);
    setError("");
    setNotice("");
    try {
      const result = await api<{ cleanup_pending: boolean }>(`${path}/${id}`, {
        method: "DELETE",
        body: JSON.stringify({ expected_updated_at: updatedAt }),
      });
      if (generation.current !== current) return;
      setPendingCleanup(result.cleanup_pending ? id : undefined);
      setNotice(
        result.cleanup_pending
          ? "附件已不可下载，磁盘清理尚未完成，可重试清理。"
          : "附件已删除。",
      );
      setRevision((v) => v + 1);
      await onChanged();
    } catch (e) {
      if (generation.current !== current) return;
      setError(
        e instanceof Error ? e.message : "删除结果未确认，请刷新后重试。",
      );
      if ((e as Error & { status?: number }).status === 409) {
        try {
          await onChanged();
          setRevision((v) => v + 1);
        } catch {
          setNotice("刷新未完成，请刷新工单后再重试删除。");
        }
      }
    } finally {
      if (generation.current === current) setBusy(false);
      onBusyChange(false);
    }
  }
  async function older() {
    if (!data?.has_more || busy || loading || disabled) return;
    const current = generation.current;
    setBusy(true);
    onBusyChange(true);
    setError("");
    try {
      const page = await api<Page>(`${path}?before=${data.next_before}`);
      if (generation.current === current)
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
    } catch (e) {
      if (generation.current === current)
        setError(e instanceof Error ? e.message : "附件读取失败");
    } finally {
      if (generation.current === current) setBusy(false);
      onBusyChange(false);
    }
  }
  return (
    <section className="ticket-attachments" aria-label="私有工单附件">
      <h3>
        <Paperclip size={16} /> 工单附件
      </h3>
      <p className="panel-footnote">
        对本工单报障人与支持团队可见，请先移除敏感内容。支持 PNG / JPEG / UTF-8
        TXT、LOG，单份最多 5 MiB，每张工单最多 20 份。
      </p>
      {loading && (
        <p role="status" className="panel-footnote">
          正在读取附件…
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
      {data?.items.length ? (
        <ul className="attachment-list">
          {data.items.map((item) => (
            <li key={item.id}>
              <div className="attachment-meta">
                <strong>{item.filename}</strong>
                <small>
                  {(item.size_bytes / 1024).toFixed(1)} KiB ·{" "}
                  {item.uploader_name} ·{" "}
                  {new Date(item.created_at).toLocaleString("zh-CN", {
                    timeZone: "Asia/Hong_Kong",
                  })}
                </small>
              </div>
              <div className="attachment-actions">
                <button
                  type="button"
                  className="secondary"
                  disabled={busy || disabled}
                  onClick={() => download(item)}
                  aria-label={`下载 ${item.filename}`}
                >
                  <Download size={14} />
                  下载
                </button>
                {item.can_delete && (
                  <button
                    type="button"
                    className="text-button"
                    disabled={busy || disabled}
                    onClick={() => remove(item.id)}
                    aria-label={`删除 ${item.filename}`}
                  >
                    <Trash2 size={14} />
                    删除
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        data && <p className="panel-footnote">暂无附件。</p>
      )}
      {data?.has_more && (
        <button
          className="secondary"
          disabled={busy || disabled || loading}
          onClick={older}
        >
          加载更早附件
        </button>
      )}
      {pendingCleanup && (
        <button
          className="secondary"
          disabled={busy || disabled}
          onClick={() => remove(pendingCleanup)}
        >
          重试磁盘清理
        </button>
      )}
      {data?.can_upload ? (
        <form className="attachment-upload" onSubmit={upload}>
          <label htmlFor={`attachment-${scope}-${ticketId}`}>
            选择附件
            <input
              ref={input}
              id={`attachment-${scope}-${ticketId}`}
              type="file"
              accept=".png,.jpg,.jpeg,.txt,.log"
              disabled={busy || disabled}
              onChange={(event) => {
                setFile(event.target.files?.[0]);
                pending.current = undefined;
                setHasPendingUpload(false);
                setError("");
              }}
            />
          </label>
          <button
            className="secondary"
            disabled={!file || busy || disabled || loading}
          >
            <Upload size={14} />
            {busy ? "正在处理…" : hasPendingUpload ? "重试原上传" : "上传附件"}
          </button>
        </form>
      ) : (
        data && (
          <p className="panel-footnote">
            当前工单状态或接手权限不允许新增附件，已有附件仍可下载。
          </p>
        )
      )}
    </section>
  );
}
