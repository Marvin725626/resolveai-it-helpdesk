import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowRight, Layers, ShieldCheck } from "lucide-react";

type InviteStatus = "checking" | "ready" | "invalid";

export default function InviteAccept() {
  const [token, setToken] = useState("");
  const [status, setStatus] = useState<InviteStatus>("checking");
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const didReadFragment = useRef(false);

  useEffect(() => {
    if (didReadFragment.current) return;
    didReadFragment.current = true;
    const fragment = window.location.hash.slice(1);
    const value = fragment.startsWith("token=") ? fragment.slice(6) : fragment;
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${window.location.search}`,
    );
    let extracted = "";
    try {
      extracted = decodeURIComponent(value);
    } catch {
      setStatus("invalid");
      return;
    }
    setToken(extracted);
    if (!extracted) {
      setStatus("invalid");
      return;
    }
    fetch("/api/v1/auth/invitations/lookup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: extracted }),
    })
      .then((response) => setStatus(response.ok ? "ready" : "invalid"))
      .catch(() => setStatus("invalid"));
  }, []);

  async function accept(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/v1/auth/invitations/accept", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, email, full_name: fullName, password }),
      });
      const body = await response.json();
      if (!response.ok)
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : "邀请无法使用，请联系工作区管理员。",
        );
      localStorage.setItem("resolveai_token", body.access_token);
      window.location.replace("/");
    } catch (e) {
      setError(e instanceof Error ? e.message : "加入工作区失败。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-screen invite-screen">
      <div className="login-story">
        <a className="brand" href="/">
          <span className="brand-mark">
            <Layers size={23} />
          </span>
          ResolveAI<span className="beta">IT</span>
        </a>
        <div className="login-copy">
          <span className="eyebrow light">SUPPORT WORKSPACE</span>
          <h1>加入支持团队</h1>
          <p>设置个人账号，开始参与工作区中的 IT 支持与工单处理。</p>
        </div>
        <small>邀请链接为一次性凭证，请勿转发给其他人。</small>
      </div>
      <div className="login-panel">
        <div className="login-form-wrap">
          <span className="eyebrow">WORKSPACE INVITATION</span>
          <h2>
            {status === "checking"
              ? "正在验证邀请…"
              : status === "ready"
                ? "创建你的账号"
                : "邀请链接不可用"}
          </h2>
          {status === "ready" ? (
            <>
              <p className="muted">
                请使用邀请发送到的邮箱。你将以支持专员身份加入。
              </p>
              <form onSubmit={accept}>
                <label>
                  受邀邮箱
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoComplete="email"
                  />
                </label>
                <label>
                  显示姓名
                  <input
                    type="text"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    required
                    maxLength={100}
                    autoComplete="name"
                  />
                </label>
                <label>
                  设置密码
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    minLength={8}
                    autoComplete="new-password"
                  />
                </label>
                <p className="invite-password-hint">
                  密码需至少 8 位，并包含大小写字母、数字和符号。
                </p>
                {error && (
                  <div className="error" role="alert">
                    {error}
                  </div>
                )}
                <button className="primary login-button" disabled={busy}>
                  {busy ? "正在加入…" : "接受邀请并进入工作台"}
                  <ArrowRight size={18} />
                </button>
              </form>
              <div className="demo-note">
                <ShieldCheck size={19} />
                <div>
                  <strong>手动邀请流程</strong>
                  <span>
                    系统不会发送邮件或验证邮箱归属。确认邀请链接来自你的工作区管理员。
                  </span>
                </div>
              </div>
            </>
          ) : (
            <p className="muted" role="status">
              {status === "checking"
                ? "请稍候。"
                : "邀请可能已过期、撤销或已被使用。请联系工作区管理员重新邀请。"}
            </p>
          )}
        </div>
      </div>
    </main>
  );
}
