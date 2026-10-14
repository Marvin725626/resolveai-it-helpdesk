import { useEffect, useState } from "react";
import { Ban, Clipboard, MailPlus, RefreshCw, Users } from "lucide-react";

type Api = <T>(path: string, init?: RequestInit) => Promise<T>;
type Member = {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
};
type Invitation = {
  id: string;
  email: string;
  status: string;
  created_at: string;
  expires_at: string;
  consumed_at?: string | null;
  revoked_at?: string | null;
};
type Roster = { members: Member[]; invitations: Invitation[] };

const date = (value: string) => new Date(value).toLocaleString();
const roleName: Record<string, string> = {
  TENANT_OWNER: "工作区所有者",
  TENANT_ADMIN: "管理员",
  SUPPORT_AGENT: "支持专员",
};
const statusName: Record<string, string> = {
  pending: "待接受",
  accepted: "已接受",
  expired: "已过期",
  revoked: "已撤销",
};

export default function TeamPage({ api }: { api: Api }) {
  const [roster, setRoster] = useState<Roster>();
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [inviteLink, setInviteLink] = useState("");
  const [copied, setCopied] = useState(false);

  async function reload() {
    setError("");
    try {
      setRoster(await api<Roster>("/auth/invitations"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "无法读取团队信息。");
    }
  }
  useEffect(() => {
    void reload();
  }, []);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setInviteLink("");
    setCopied(false);
    try {
      const invite = await api<{ token: string }>("/auth/invitations", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      setInviteLink(
        `${window.location.origin}/invite#${encodeURIComponent(invite.token)}`,
      );
      setEmail("");
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "无法创建邀请。");
    } finally {
      setLoading(false);
    }
  }
  async function revoke(id: string) {
    setError("");
    try {
      await api(`/auth/invitations/${id}`, { method: "DELETE" });
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "无法撤销邀请。");
    }
  }
  async function copyLink() {
    try {
      await navigator.clipboard.writeText(inviteLink);
      setCopied(true);
    } catch {
      setError("复制失败，请手动复制显示的邀请链接。");
    }
  }

  return (
    <div className="team-page">
      <section className="panel">
        <div className="panel-title">
          <span className="title-icon">
            <Users size={19} />
          </span>
          <div>
            <h2>工作区成员</h2>
            <p>成员加入后会出现在工单分配选项中。</p>
          </div>
          <button
            className="secondary"
            type="button"
            onClick={() => void reload()}
            aria-label="刷新成员"
          >
            <RefreshCw size={16} />
            刷新
          </button>
        </div>
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        <div className="team-table-wrap">
          <table className="team-table">
            <thead>
              <tr>
                <th>姓名</th>
                <th>工作邮箱</th>
                <th>角色</th>
                <th>加入时间</th>
              </tr>
            </thead>
            <tbody>
              {(roster?.members ?? []).map((member) => (
                <tr key={member.id}>
                  <td>{member.full_name}</td>
                  <td>{member.email}</td>
                  <td>{roleName[member.role] ?? member.role}</td>
                  <td>{date(member.created_at)}</td>
                </tr>
              ))}
              {!roster?.members.length && (
                <tr>
                  <td colSpan={4}>正在读取成员…</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
      <section className="panel team-invite-panel">
        <div className="panel-title">
          <span className="title-icon">
            <MailPlus size={19} />
          </span>
          <div>
            <h2>邀请支持专员</h2>
            <p>新成员将固定获得支持专员权限。</p>
          </div>
        </div>
        <form className="team-invite-form" onSubmit={create}>
          <label htmlFor="invite-email">工作邮箱</label>
          <div className="team-invite-controls">
            <input
              id="invite-email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="agent@example.com"
            />
            <button className="primary" disabled={loading}>
              {loading ? "正在创建…" : "创建邀请"}
              <MailPlus size={16} />
            </button>
          </div>
        </form>
        <div className="config-note">
          <strong>手动发送邀请链接</strong>
          <p>
            系统不会发送邮件。请通过你信任的渠道把链接交给受邀者。链接 48
            小时后失效，受邀者需填写同一邮箱、姓名并自行设置密码。此流程不会验证收件人是否实际控制该邮箱。
          </p>
        </div>
        {inviteLink && (
          <div className="invite-link-box">
            <label htmlFor="new-invite-link">新邀请链接（仅此时显示）</label>
            <div className="team-invite-controls">
              <input
                id="new-invite-link"
                readOnly
                value={inviteLink}
                onFocus={(e) => e.currentTarget.select()}
              />
              <button
                type="button"
                className="secondary"
                onClick={() => void copyLink()}
              >
                <Clipboard size={16} />
                {copied ? "已复制" : "复制链接"}
              </button>
            </div>
            <small>请立即复制并发送。离开本页后无法再次查看此链接。</small>
          </div>
        )}
      </section>
      <section className="panel">
        <div className="panel-title">
          <div>
            <h2>邀请记录</h2>
            <p>待接受邀请可以随时撤销。</p>
          </div>
        </div>
        <div className="team-table-wrap">
          <table className="team-table">
            <thead>
              <tr>
                <th>受邀邮箱</th>
                <th>状态</th>
                <th>创建时间</th>
                <th>有效期至</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(roster?.invitations ?? []).map((invite) => (
                <tr key={invite.id}>
                  <td>{invite.email}</td>
                  <td>{statusName[invite.status] ?? invite.status}</td>
                  <td>{date(invite.created_at)}</td>
                  <td>{date(invite.expires_at)}</td>
                  <td>
                    {invite.status === "pending" && (
                      <button
                        className="secondary danger-button"
                        type="button"
                        onClick={() => void revoke(invite.id)}
                      >
                        <Ban size={15} />
                        撤销
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {roster && roster.invitations.length === 0 && (
                <tr>
                  <td colSpan={5}>尚无邀请记录。</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
