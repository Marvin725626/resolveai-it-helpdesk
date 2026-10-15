import { useEffect, useState, type FormEvent } from "react";
import { BookOpenCheck, Send } from "lucide-react";

type Api = <T>(path: string, init?: RequestInit) => Promise<T>;
type Resolution = {
  id: string;
  ticket_id: string;
  category: string;
  summary: string;
  steps: string | string[];
  author_name: string;
  resolved_at: string;
};
type ResolutionResponse = {
  resolution: Resolution | null;
  current: boolean;
  updated_at: string;
};
type DraftBody = {
  request_id: string;
  resolution_id: string;
  title: string;
  content: string;
  keywords: string;
};
const categoryLabel: Record<string, string> = {
  configuration: "配置",
  account_access: "账号权限",
  software: "软件",
  service: "服务",
  guidance: "操作指导",
  other: "其他",
};
const stepList = (steps: string | string[]) =>
  Array.isArray(steps)
    ? steps
    : steps
        .split(/\r?\n/)
        .map((step) => step.trim())
        .filter(Boolean);

export default function KnowledgeDraftAction({
  api,
  ticketId,
  resolutionId,
}: {
  api: Api;
  ticketId: string;
  resolutionId: string;
}) {
  const [resolution, setResolution] = useState<Resolution>();
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [keywords, setKeywords] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [current, setCurrent] = useState(false);
  const [pending, setPending] = useState<DraftBody>();
  useEffect(() => {
    let active = true;
    api<ResolutionResponse>(`/helpdesk/tickets/${ticketId}/resolution`)
      .then((result) => {
        if (!active) return;
        const snapshot = result.resolution;
        if (!snapshot || snapshot.id !== resolutionId) {
          setError("找不到这条解决快照，请刷新工单。");
          return;
        }
        setResolution(snapshot);
        setCurrent(result.current);
        setTitle(
          `解决方案：${categoryLabel[snapshot.category] || snapshot.category}`,
        );
        const steps = stepList(snapshot.steps);
        setContent(
          [
            `问题摘要：${snapshot.summary}`,
            "",
            "处理步骤：",
            ...steps.map((step, index) => `${index + 1}. ${step}`),
          ].join("\n"),
        );
      })
      .catch(
        (e) =>
          active &&
          setError(e instanceof Error ? e.message : "解决快照载入失败"),
      );
    return () => {
      active = false;
    };
  }, [ticketId, resolutionId]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (
      !resolution ||
      !current ||
      busy ||
      title.trim().length < 2 ||
      content.trim().length < 20
    )
      return;
    const next = {
      resolution_id: resolution.id,
      title: title.trim(),
      content: content.trim(),
      keywords: keywords.trim(),
    };
    const request =
      pending &&
      pending.resolution_id === next.resolution_id &&
      pending.title === next.title &&
      pending.content === next.content &&
      pending.keywords === next.keywords
        ? pending
        : { ...next, request_id: crypto.randomUUID() };
    setPending(request);
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await api("/helpdesk/knowledge-drafts", {
        method: "POST",
        body: JSON.stringify(request),
      });
      setMessage("知识草稿已保存，等待工作区管理员审核；草稿不会参与检索。");
    } catch (e) {
      setError(e instanceof Error ? e.message : "草稿保存失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="knowledge-draft-action">
      <h3>
        <BookOpenCheck size={17} />
        整理为知识草稿
      </h3>
      {!resolution && !error && <p role="status">正在读取公开解决快照…</p>}
      {resolution && (
        <>
          <div className="knowledge-draft-resolution">
            <span>
              {categoryLabel[resolution.category] || resolution.category}
            </span>
            <p>{resolution.summary}</p>
            <ol>
              {stepList(resolution.steps).map((step, index) => (
                <li key={`${index}-${step}`}>{step}</li>
              ))}
            </ol>
          </div>
          {!current && (
            <p className="panel-footnote">
              该解决快照已过期，当前只读；请使用最新处理结果创建草稿。
            </p>
          )}
          {current && (
            <form className="knowledge-draft-form" onSubmit={submit}>
              <label>
                草稿标题
                <input
                  value={title}
                  onChange={(event) => {
                    setTitle(event.target.value);
                    setPending(undefined);
                  }}
                  minLength={2}
                  maxLength={200}
                  required
                  disabled={busy}
                />
              </label>
              <label>
                知识正文
                <textarea
                  value={content}
                  onChange={(event) => {
                    setContent(event.target.value);
                    setPending(undefined);
                  }}
                  minLength={20}
                  maxLength={15000}
                  required
                  disabled={busy}
                />
              </label>
              <label>
                检索关键词
                <input
                  value={keywords}
                  onChange={(event) => {
                    setKeywords(event.target.value);
                    setPending(undefined);
                  }}
                  maxLength={500}
                  disabled={busy}
                  placeholder="用空格或逗号分隔"
                />
              </label>
              <button
                className="secondary"
                disabled={
                  busy || title.trim().length < 2 || content.trim().length < 20
                }
              >
                {busy ? "正在保存…" : "保存知识草稿"}
                <Send size={14} />
              </button>
            </form>
          )}
        </>
      )}
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {message && (
        <p className="success-message" role="status">
          {message}
        </p>
      )}
    </section>
  );
}
