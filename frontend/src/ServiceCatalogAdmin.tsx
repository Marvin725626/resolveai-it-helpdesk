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
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(false);
  const [answers, setAnswers] = useState<Record<string, string>>({});

  async function refresh(prefer = selected) {
    const result = await apiRef.current<{ items: Item[] }>(
      "/helpdesk/service-catalog-admin",
    );
    setItems(result.items);
    const next = result.items.find((x) => x.id === prefer) ?? result.items[0];
    if (next) {
      setSelected(next.id);
      setDraft(next);
      setIsNew(false);
    } else if (!prefer) {
      setSelected("");
      setDraft(blank());
      setIsNew(true);
    }
  }
  useEffect(() => {
    void refresh("").catch((e) =>
      setError(e instanceof Error ? e.message : "目录加载失败"),
    );
  }, []);
  useEffect(() => {
    if (!selected) {
      setRevisions([]);
      return;
    }
    void apiRef
      .current<{ revisions: Revision[] }>(
        `/helpdesk/service-catalog-admin/${selected}/revisions`,
      )
      .then((r) => setRevisions(r.revisions))
      .catch(() => setRevisions([]));
  }, [selected]);
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
    try {
      if (isNew) {
        const body = { ...draft, request_id: crypto.randomUUID() };
        const result = await api<{ item: Item }>(
          "/helpdesk/service-catalog-admin",
          { method: "POST", body: JSON.stringify(body) },
        );
        setNotice("服务目录项已创建。");
        await refresh(result.item.id);
      } else {
        const current = draft as Item;
        const result = await api<{ item: Item }>(
          `/helpdesk/service-catalog-admin/${current.id}`,
          {
            method: "PUT",
            body: JSON.stringify({
              ...draft,
              expected_version: current.version,
            }),
          },
        );
        setNotice("服务目录项已保存。");
        await refresh(result.item.id);
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : "保存失败";
      setError(
        message.includes("409")
          ? "版本冲突：目录已被其他管理员更新。请刷新后重新编辑。"
          : message,
      );
    } finally {
      setBusy(false);
    }
  }
  async function reload() {
    setError("");
    try {
      await refresh(selected);
      setNotice("目录已刷新。");
    } catch (e) {
      setError(e instanceof Error ? e.message : "刷新失败");
    }
  }
  function newItem() {
    setSelected("");
    setIsNew(true);
    setDraft(blank());
    setRevisions([]);
    setAnswers({});
    setError("");
    setNotice("");
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
            onClick={() => void reload()}
          >
            刷新
          </button>
          <button type="button" onClick={newItem}>
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
      <div className="catalog-layout">
        <nav className="catalog-list" aria-label="服务目录项">
          {items.map((item) => (
            <button
              type="button"
              key={item.id}
              className={selected === item.id ? "selected" : ""}
              onClick={() => {
                setSelected(item.id);
                setDraft(item);
                setIsNew(false);
                setError("");
                setNotice("");
              }}
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
                disabled={fields.length >= 6}
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
              <fieldset className="catalog-field" key={index}>
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
            <section className="catalog-history">
              <h3>历史修订</h3>
              {revisions.map((rev) => (
                <details key={rev.version}>
                  <summary>
                    v{rev.version} · {rev.actor_name} ·{" "}
                    {new Date(rev.created_at).toLocaleString()}
                  </summary>
                  <pre>{JSON.stringify(rev.snapshot, null, 2)}</pre>
                </details>
              ))}
            </section>
          )}
        </div>
      </div>
    </section>
  );
}
