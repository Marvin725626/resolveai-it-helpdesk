import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import "./catalog.css";

type Api = <T>(path: string, init?: RequestInit) => Promise<T>;
type Field = {
  key: string;
  label: string;
  type: "text" | "textarea" | "select";
  required: boolean;
  options?: string[];
};
type Item = {
  id: string;
  code: string;
  title: string;
  summary: string;
  category: string;
  fields: Field[];
  status: string;
  version: number;
  created_at?: string;
  updated_at?: string;
};
type Revision = {
  version: number;
  snapshot: Item;
  actor_name: string;
  created_at: string;
};
const blank = (): Omit<Item, "id" | "version"> => ({
  code: "",
  title: "",
  summary: "",
  category: "other",
  fields: [],
  status: "draft",
});

export default function ServiceCatalogAdmin({ api }: { api: Api }) {
  const apiRef = useRef(api);
  apiRef.current = api;
  const [items, setItems] = useState<Item[]>([]);
  const [selected, setSelected] = useState("");
  const [draft, setDraft] = useState<Item | Omit<Item, "id" | "version">>(
    blank(),
  );
  const [isNew, setIsNew] = useState(true);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [historyError, setHistoryError] = useState(false);
  const [historyReload, setHistoryReload] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(true);
  const [preview, setPreview] = useState(false);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [pendingAction, setPendingAction] = useState<
    | { type: "item"; item: Item }
    | { type: "new" | "reload" | "copy" }
    | { type: "restore"; revision: Revision }
    | null
  >(null);
  const [copied, setCopied] = useState(false);
  const createRequest = useRef<{ signature: string; id: string } | null>(null);
  const revisionsRequest = useRef(0);
  const [savedItem, setSavedItem] = useState<Item | null>(null);

  function contentOf(value: Item | Omit<Item, "id" | "version">) {
    return {
      code: value.code,
      title: value.title,
      summary: value.summary,
      category: value.category,
      fields: value.fields.map((field) => ({
        key: field.key,
        label: field.label,
        type: field.type,
        required: field.required,
        ...(field.options ? { options: [...field.options] } : {}),
      })),
      status: value.status,
    };
  }
  const dirty = useMemo(
    () =>
      !!savedItem &&
      JSON.stringify(contentOf(draft)) !== JSON.stringify(contentOf(savedItem)),
    [draft, savedItem],
  );
  const newDirty = useMemo(
    () =>
      isNew &&
      JSON.stringify(contentOf(draft)) !== JSON.stringify(contentOf(blank())),
    [draft, isNew],
  );
  const hasUnsaved = dirty || newDirty;

  async function refresh(prefer = selected) {
    const result = await apiRef.current<{ items: Item[] }>(
      "/helpdesk/service-catalog-admin",
    );
    setItems(result.items);
    const next = result.items.find((x) => x.id === prefer) ?? result.items[0];
    if (next) {
      if (selected !== next.id) {
        revisionsRequest.current++;
        setRevisions([]);
        setHistoryError(false);
      }
      setSelected(next.id);
      setDraft(next);
      setIsNew(false);
      setSavedItem(next);
    } else if (!prefer) {
      revisionsRequest.current++;
      setSelected("");
      setDraft(blank());
      setIsNew(true);
      setSavedItem(null);
    }
  }
  useEffect(() => {
    void refresh("")
      .catch((e) => setError(e instanceof Error ? e.message : "目录加载失败"))
      .finally(() => setBusy(false));
  }, []);
  useEffect(() => {
    const requestId = ++revisionsRequest.current;
    if (!selected) {
      setRevisions([]);
      setHistoryError(false);
      return;
    }
    setHistoryError(false);
    void apiRef
      .current<{ revisions: Revision[] }>(
        `/helpdesk/service-catalog-admin/${selected}/revisions`,
      )
      .then((r) => {
        if (requestId === revisionsRequest.current) setRevisions(r.revisions);
      })
      .catch(() => {
        if (requestId === revisionsRequest.current) {
          setRevisions([]);
          setHistoryError(true);
        }
      });
  }, [selected, historyReload]);
  const fields = draft.fields;
  const canSave = useMemo(
    () =>
      !busy && draft.title.trim().length >= 2 && draft.code.trim().length >= 2,
    [busy, draft],
  );
  function edit<K extends keyof typeof draft>(
    key: K,
    value: (typeof draft)[K],
  ) {
    setDraft((old) => ({ ...old, [key]: value }));
  }
  function updateField(index: number, patch: Partial<Field>) {
    setDraft((old) => ({
      ...old,
      fields: old.fields.map((f, i) => (i === index ? { ...f, ...patch } : f)),
    }));
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!canSave) return;
    setBusy(true);
    setError("");
    setNotice("");
    let saved: Item;
    try {
      if (isNew) {
        const content = contentOf(draft);
        const signature = JSON.stringify(content);
        if (
          !createRequest.current ||
          createRequest.current.signature !== signature
        ) {
          createRequest.current = { signature, id: crypto.randomUUID() };
        }
        const result = await api<{ item: Item }>(
          "/helpdesk/service-catalog-admin",
          {
            method: "POST",
            body: JSON.stringify({
              ...content,
              request_id: createRequest.current.id,
            }),
          },
        );
        createRequest.current = null;
        saved = result.item;
      } else {
        const current = draft as Item;
        const result = await api<{ item: Item }>(
          `/helpdesk/service-catalog-admin/${current.id}`,
          {
            method: "PUT",
            body: JSON.stringify({
              ...contentOf(draft),
              expected_version: current.version,
            }),
          },
        );
        saved = result.item;
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : "保存失败";
      const status =
        typeof e === "object" && e !== null && "status" in e
          ? (e as { status?: number }).status
          : undefined;
      setError(
        status === 409 || message.includes("409")
          ? "版本冲突：目录已被其他管理员更新。请刷新后重新编辑。"
          : message,
      );
      setBusy(false);
      return;
    }
    setPendingAction(null);
    setPreview(false);
    setAnswers({});
    setSelected(saved.id);
    setDraft(saved);
    setSavedItem(saved);
    setIsNew(false);
    setCopied(false);
    setItems((old) =>
      old.some((item) => item.id === saved.id)
        ? old.map((item) => (item.id === saved.id ? saved : item))
        : [...old, saved],
    );
    setNotice(isNew ? "服务目录项已创建。" : "服务目录项已保存。");
    setError("");
    try {
      await refresh(saved.id);
    } catch (e) {
      setError(
        `服务已保存，但目录列表刷新失败：${e instanceof Error ? e.message : "刷新失败"}`,
      );
    }
    const historyId = ++revisionsRequest.current;
    try {
      const latest = await api<{ revisions: Revision[] }>(
        `/helpdesk/service-catalog-admin/${saved.id}/revisions`,
      );
      if (historyId === revisionsRequest.current) {
        setRevisions(latest.revisions);
        setHistoryError(false);
      }
    } catch {
      if (historyId === revisionsRequest.current) {
        setHistoryError(true);
        setError((old) =>
          old
            ? `${old} 历史修订加载失败，可在历史区域重试。`
            : "服务已保存，但历史修订加载失败，可在历史区域重试。",
        );
      }
    } finally {
      setBusy(false);
    }
  }
  async function reload() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await refresh(selected);
      setHistoryReload((n) => n + 1);
      setNotice("目录已刷新。");
    } catch (e) {
      setError(e instanceof Error ? e.message : "刷新失败");
    } finally {
      setBusy(false);
    }
  }
  function newItem() {
    if (busy) return;
    requestAction({ type: "new" });
  }
  function startNew() {
    createRequest.current = null;
    revisionsRequest.current++;
    setSelected("");
    setIsNew(true);
    setDraft(blank());
    setSavedItem(null);
    setRevisions([]);
    setHistoryError(false);
    setAnswers({});
    setPreview(false);
    setError("");
    setNotice("");
    setCopied(false);
  }
  function selectItem(item: Item) {
    if (busy) return;
    requestAction({ type: "item", item });
  }
  function loadItem(item: Item) {
    if (selected !== item.id) {
      revisionsRequest.current++;
      setRevisions([]);
      setHistoryError(false);
    }
    setSelected(item.id);
    setDraft(item);
    setSavedItem(item);
    setIsNew(false);
    setCopied(false);
    setError("");
    setNotice("");
    setAnswers({});
    setPreview(false);
  }
  function resolvePending(keep: boolean) {
    if (keep) {
      setPendingAction(null);
      return;
    }
    if (pendingAction) void performAction(pendingAction);
    setPendingAction(null);
  }
  function restoreRevision(rev: Revision) {
    requestAction({ type: "restore", revision: rev });
  }
  function applyRevision(rev: Revision) {
    const snapshot = rev.snapshot;
    setDraft((old) => ({
      ...old,
      title: snapshot.title,
      summary: snapshot.summary,
      category: snapshot.category,
      fields: snapshot.fields.map((f) => ({
        ...f,
        options: f.options ? [...f.options] : undefined,
      })),
    }));
    setNotice(
      `已将 v${rev.version} 的内容载入编辑器。点击保存会生成新版本；旧申请保持不变。`,
    );
    setAnswers({});
    setPreview(false);
  }
  function copyAsNew() {
    requestAction({ type: "copy" });
  }
  function applyCopy() {
    createRequest.current = null;
    const current = savedItem;
    if (!current) return;
    revisionsRequest.current++;
    const copyTitle = Array.from(`${current.title}（副本）`)
      .slice(0, 120)
      .join("");
    setDraft({
      ...contentOf(current),
      code: "",
      title: copyTitle,
      status: "draft",
    });
    setSelected("");
    setIsNew(true);
    setSavedItem(null);
    setRevisions([]);
    setAnswers({});
    setPreview(false);
    setCopied(true);
    setNotice(
      "副本已准备为新草稿。填写新的服务代码后，点击“创建服务”明确创建。",
    );
  }
  type PendingAction =
    | { type: "item"; item: Item }
    | { type: "new" | "reload" | "copy" }
    | { type: "restore"; revision: Revision };
  function requestAction(action: PendingAction) {
    if (busy) return;
    if (hasUnsaved) {
      setPendingAction(action);
      return;
    }
    void performAction(action);
  }
  async function performAction(action: PendingAction) {
    if (action.type === "item") loadItem(action.item);
    else if (action.type === "new") startNew();
    else if (action.type === "reload") await reload();
    else if (action.type === "copy") applyCopy();
    else if (action.type === "restore") applyRevision(action.revision);
  }

  return (
    <section className="panel service-catalog-admin">
      <div className="panel-title">
        <div>
          <h2>服务目录管理</h2>
          <p>维护员工可提交的 IT 服务申请模板。</p>
        </div>
        <div className="catalog-toolbar">
          <button
            type="button"
            className="secondary-button"
            disabled={busy}
            onClick={() => requestAction({ type: "reload" })}
          >
            刷新
          </button>
          <button type="button" onClick={newItem} disabled={busy}>
            新增服务
          </button>
        </div>
      </div>
      {error && (
        <p className="catalog-message error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="catalog-message" role="status">
          {notice}
        </p>
      )}
      {hasUnsaved && pendingAction && (
        <div className="catalog-message catalog-unsaved" role="alert">
          <span>当前编辑有未保存的更改。选择继续操作会放弃这些更改。</span>
          <button
            type="button"
            disabled={busy}
            onClick={() => resolvePending(false)}
          >
            放弃更改并继续
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={busy}
            onClick={() => resolvePending(true)}
          >
            保留编辑
          </button>
        </div>
      )}
      <div className="catalog-layout">
        <nav className="catalog-list" aria-label="服务目录项">
          {items.map((item) => (
            <button
              type="button"
              key={item.id}
              className={selected === item.id ? "selected" : ""}
              disabled={busy}
              onClick={() => selectItem(item)}
            >
              <strong>{item.title}</strong>
              <span>
                {item.code} · {item.status} · v{item.version}
              </span>
            </button>
          ))}
          {!items.length && (
            <p className="panel-footnote">尚无目录项，请新增服务。</p>
          )}
        </nav>
        <div className="catalog-editor">
          <form onSubmit={(e) => void save(e)}>
            <div className="catalog-form-grid">
              <label>
                服务代码
                <input
                  required
                  disabled={busy}
                  maxLength={40}
                  value={draft.code}
                  readOnly={!isNew}
                  title={!isNew ? "服务代码创建后保持固定" : undefined}
                  onChange={(e) => edit("code", e.target.value)}
                />
              </label>
              <label>
                服务名称
                <input
                  required
                  disabled={busy}
                  minLength={2}
                  maxLength={120}
                  value={draft.title}
                  onChange={(e) => edit("title", e.target.value)}
                />
              </label>
              <label>
                分类
                <select
                  value={draft.category}
                  disabled={busy}
                  onChange={(e) => edit("category", e.target.value)}
                >
                  {[
                    ["network", "网络"],
                    ["account", "账号"],
                    ["software", "软件"],
                    ["hardware", "硬件"],
                    ["other", "其他"],
                  ].map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                状态
                <select
                  value={draft.status}
                  disabled={busy || copied}
                  onChange={(e) => edit("status", e.target.value)}
                >
                  <option value="draft">草稿</option>
                  <option value="published">发布</option>
                  {!isNew && <option value="archived">归档</option>}
                </select>
              </label>
            </div>
            <label>
              简介
              <textarea
                rows={3}
                disabled={busy}
                maxLength={1000}
                value={draft.summary}
                onChange={(e) => edit("summary", e.target.value)}
              />
            </label>
            <div className="catalog-fields-heading">
              <h3>申请字段（最多 6 项）</h3>
              <button
                type="button"
                className="secondary-button"
                disabled={busy || fields.length >= 6}
                onClick={() =>
                  edit("fields", [
                    ...fields,
                    { key: "", label: "", type: "text", required: false },
                  ])
                }
              >
                添加字段
              </button>
            </div>
            {fields.map((field, index) => (
              <fieldset className="catalog-field" key={index} disabled={busy}>
                <legend>字段 {index + 1}</legend>
                <div className="catalog-form-grid">
                  <label>
                    字段标识
                    <input
                      required
                      maxLength={40}
                      value={field.key}
                      onChange={(e) =>
                        updateField(index, { key: e.target.value })
                      }
                      placeholder="例如 device_name"
                    />
                  </label>
                  <label>
                    显示名称
                    <input
                      required
                      minLength={2}
                      maxLength={80}
                      value={field.label}
                      onChange={(e) =>
                        updateField(index, { label: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    输入类型
                    <select
                      value={field.type}
                      disabled={busy}
                      onChange={(e) =>
                        updateField(index, {
                          type: e.target.value as Field["type"],
                          options:
                            e.target.value === "select" ? ["", ""] : undefined,
                        })
                      }
                    >
                      <option value="text">单行文本</option>
                      <option value="textarea">多行文本</option>
                      <option value="select">下拉选择</option>
                    </select>
                  </label>
                  <label className="catalog-check">
                    <input
                      type="checkbox"
                      disabled={busy}
                      checked={field.required}
                      onChange={(e) =>
                        updateField(index, { required: e.target.checked })
                      }
                    />
                    必填
                  </label>
                </div>
                {field.type === "select" && (
                  <label>
                    选项（每行一项，2–10 项）
                    <textarea
                      rows={3}
                      value={(field.options ?? []).join("\n")}
                      onChange={(e) =>
                        updateField(index, {
                          options: e.target.value.split("\n").slice(0, 10),
                        })
                      }
                    />
                  </label>
                )}
                <button
                  type="button"
                  className="text-button"
                  disabled={busy}
                  onClick={() =>
                    edit(
                      "fields",
                      fields.filter((_, i) => i !== index),
                    )
                  }
                >
                  删除字段
                </button>
              </fieldset>
            ))}
            <div className="catalog-actions">
              <button type="submit" disabled={!canSave}>
                {busy ? "保存中…" : isNew ? "创建服务" : "保存修改"}
              </button>
              <button
                type="button"
                className="secondary-button"
                disabled={busy}
                onClick={() => {
                  setPreview((v) => !v);
                  setAnswers({});
                }}
              >
                {preview ? "关闭预览" : "预览申请表"}
              </button>
            </div>
          </form>
          {preview && (
            <section className="catalog-preview">
              <h3>员工申请表预览</h3>
              <h4>{draft.title || "服务名称"}</h4>
              <p>{draft.summary}</p>
              {fields.map((field) => (
                <label key={field.key}>
                  {field.label || "未命名字段"}
                  {field.required ? " *" : ""}
                  {field.type === "select" ? (
                    <select
                      value={answers[field.key] ?? ""}
                      onChange={(e) =>
                        setAnswers({ ...answers, [field.key]: e.target.value })
                      }
                    >
                      <option value="">请选择</option>
                      {(field.options ?? []).filter(Boolean).map((o) => (
                        <option key={o}>{o}</option>
                      ))}
                    </select>
                  ) : field.type === "textarea" ? (
                    <textarea
                      rows={3}
                      value={answers[field.key] ?? ""}
                      onChange={(e) =>
                        setAnswers({ ...answers, [field.key]: e.target.value })
                      }
                    />
                  ) : (
                    <input
                      value={answers[field.key] ?? ""}
                      onChange={(e) =>
                        setAnswers({ ...answers, [field.key]: e.target.value })
                      }
                    />
                  )}
                </label>
              ))}
            </section>
          )}
          {!isNew && (
            <section className="catalog-history" aria-label="服务修订历史">
              <h3>历史修订</h3>
              {historyError && (
                <p className="catalog-message error" role="alert">
                  历史修订加载失败。
                  <button
                    type="button"
                    className="text-button"
                    disabled={busy}
                    onClick={() => setHistoryReload((n) => n + 1)}
                  >
                    重试历史
                  </button>
                </p>
              )}
              {revisions.map((rev) => (
                <details key={rev.version}>
                  <summary>
                    v{rev.version} · {rev.actor_name} ·{" "}
                    {new Date(rev.created_at).toLocaleString()}
                  </summary>
                  <RevisionView
                    revision={rev}
                    current={savedItem}
                    onRestore={() => restoreRevision(rev)}
                    disabled={busy}
                  />
                </details>
              ))}
            </section>
          )}
          {!isNew && (
            <button
              type="button"
              className="secondary-button"
              disabled={busy}
              onClick={copyAsNew}
            >
              复制为新草稿
            </button>
          )}
        </div>
      </div>
    </section>
  );
}

function RevisionView({
  revision,
  current,
  onRestore,
  disabled,
}: {
  revision: Revision;
  current: Item | null;
  onRestore: () => void;
  disabled: boolean;
}) {
  const snapshot = revision.snapshot;
  const categoryName: Record<string, string> = {
    network: "网络",
    account: "账号",
    software: "软件",
    hardware: "硬件",
    other: "其他",
  };
  const fieldMap = new Map(
    (snapshot.fields ?? []).map((field) => [field.key, field]),
  );
  const currentMap = new Map(
    (current?.fields ?? []).map((field) => [field.key, field]),
  );
  const added = [...fieldMap.keys()].filter((key) => !currentMap.has(key));
  const removed = [...currentMap.keys()].filter((key) => !fieldMap.has(key));
  const changed = [...fieldMap.keys()].filter((key) => {
    const before = fieldMap.get(key);
    const after = currentMap.get(key);
    return after && JSON.stringify(before) !== JSON.stringify(after);
  });
  const reordered = current
    ? [...fieldMap.keys()].filter(
        (key) =>
          currentMap.has(key) &&
          (current.fields ?? []).findIndex((field) => field.key === key) !==
            (snapshot.fields ?? []).findIndex((field) => field.key === key),
      )
    : [];
  const generalChanges = current
    ? (["title", "summary", "category", "status"] as const).filter(
        (key) => snapshot[key] !== current[key],
      )
    : [];
  const labels: Record<string, string> = {
    title: "服务名称",
    summary: "简介",
    category: "分类",
    status: "状态",
  };
  return (
    <div className="catalog-revision">
      <dl className="catalog-revision-content">
        <dt>服务名称</dt>
        <dd>{snapshot.title}</dd>
        <dt>简介</dt>
        <dd>{snapshot.summary || "无"}</dd>
        <dt>状态</dt>
        <dd>{snapshot.status}</dd>
        <dt>分类</dt>
        <dd>{categoryName[snapshot.category] ?? snapshot.category}</dd>
      </dl>
      <h4>申请字段</h4>
      {snapshot.fields?.length ? (
        <ul>
          {snapshot.fields.map((field) => (
            <li key={field.key}>
              <strong>{field.label || "未命名字段"}</strong>（{field.type}，
              {field.required ? "必填" : "选填"}）
              {field.type === "select" && (
                <span>：{(field.options ?? []).join("、")}</span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p>无申请字段。</p>
      )}
      {current && (
        <div className="catalog-revision-diff">
          <h4>对比当前已保存版本（v{current.version}）</h4>
          {!added.length &&
          !removed.length &&
          !changed.length &&
          !generalChanges.length &&
          !reordered.length ? (
            <p>无差异。</p>
          ) : (
            <ul>
              {generalChanges.map((key) => (
                <li key={key}>
                  {labels[key]}：{current[key] || "无"} →{" "}
                  {snapshot[key] || "无"}
                </li>
              ))}
              {added.map((key) => (
                <li key={`added-${key}`}>
                  新增字段：{fieldMap.get(key)?.label || key}
                </li>
              ))}
              {removed.map((key) => (
                <li key={`removed-${key}`}>
                  删除字段：{currentMap.get(key)?.label || key}
                </li>
              ))}
              {changed.map((key) => {
                const before = fieldMap.get(key)!;
                const after = currentMap.get(key)!;
                return (
                  <li key={`changed-${key}`}>
                    变更字段：{before.label || key} —{" "}
                    {fieldChanges(after, before)}
                  </li>
                );
              })}
              {reordered.length > 0 && (
                <li>
                  字段顺序：
                  {(current.fields ?? [])
                    .map((field) => field.label || field.key)
                    .join("、")}{" "}
                  →{" "}
                  {(snapshot.fields ?? [])
                    .map((field) => field.label || field.key)
                    .join("、")}
                </li>
              )}
            </ul>
          )}
        </div>
      )}
      <button
        type="button"
        className="secondary-button"
        disabled={disabled}
        onClick={onRestore}
      >
        恢复到编辑器
      </button>
    </div>
  );
}

function fieldChanges(before: Field, after: Field) {
  const labels: Record<string, string> = {
    key: "标识",
    label: "名称",
    type: "类型",
    required: "必填状态",
    options: "选项",
  };
  const changes = (["key", "label", "type", "required", "options"] as const)
    .filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]))
    .map(
      (key) =>
        `${labels[key]} ${formatFieldValue(before[key])} → ${formatFieldValue(after[key])}`,
    );
  return changes.join("；");
}

function formatFieldValue(value: unknown) {
  if (Array.isArray(value)) return value.join("、") || "无";
  if (typeof value === "boolean") return value ? "必填" : "选填";
  return String(value ?? "无");
}
