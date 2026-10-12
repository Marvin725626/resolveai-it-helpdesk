import { useEffect, useState } from "react";
import { ArrowDownToLine, Ticket } from "lucide-react";
import TicketOps, { SlaBadge, slaLabel, type TicketSummary } from "./TicketOps";
import { ticketCsv } from "./csv";
type Api = <T>(path: string, init?: RequestInit) => Promise<T>;
type Page = {
  items: TicketSummary[];
  total: number;
  page: number;
  page_size: number;
  truncated: boolean;
};
const statusLabel: Record<string, string> = {
  OPEN: "待处理",
  ESCALATED: "转人工",
  IN_PROGRESS: "处理中",
  RESOLVED: "已解决",
  CLOSED: "已关闭",
  WAITING_FOR_CUSTOMER: "等待反馈",
};
export default function TicketQueue({
  api,
  onChanged,
}: {
  api: Api;
  onChanged: () => Promise<void>;
}) {
  const [data, setData] = useState<Page>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [ticketBusy, setTicketBusy] = useState(false);
  const [ticketSla, setTicketSla] = useState("ALL");
  const [ticketStatus, setTicketStatus] = useState("ALL");
  const [ticketPriority, setTicketPriority] = useState("ALL");
  const [assignment, setAssignment] = useState("all");
  const [ticketSearch, setTicketSearch] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(20);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const timer = setTimeout(() => setSearch(ticketSearch.trim()), 300);
    return () => clearTimeout(timer);
  }, [ticketSearch]);
  const params = new URLSearchParams({ q: search, assignment });
  if (ticketStatus !== "ALL") params.set("status", ticketStatus);
  if (ticketPriority !== "ALL") params.set("priority", ticketPriority);
  if (ticketSla !== "ALL") params.set("sla", ticketSla);
  const filters = params.toString();
  params.set("page", String(page));
  params.set("page_size", String(size));
  const query = params.toString();
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    api<Page>("/helpdesk/ticket-queue?" + query)
      .then((value) => {
        if (active) {
          setData(value);
          if (page > 1 && !value.items.length)
            setPage(Math.max(1, Math.ceil(value.total / size)));
        }
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
  }, [query, revision]);
  const updating = loading || ticketSearch.trim() !== search;
  const tickets = data?.items || [];
  const filteredTickets = tickets;
  async function changed() {
    setRevision((value) => value + 1);
    await onChanged();
  }
  async function changeStatus(id: string, status: string, claim = false) {
    if (ticketBusy || loading) return;
    setTicketBusy(true);
    setError("");
    try {
      const current = tickets.find((item) => item.id === id);
      await api(`/helpdesk/tickets/${id}${claim ? "/claim" : ""}`, {
        method: claim ? "POST" : "PATCH",
        body: JSON.stringify({
          ...(claim ? {} : { status }),
          expected_updated_at: current?.updated_at,
        }),
      });
      await changed();
    } catch (e) {
      setError(e instanceof Error ? e.message : "工单更新失败");
      setRevision((value) => value + 1);
    } finally {
      setTicketBusy(false);
    }
  }
  async function exportTickets() {
    setError("");
    try {
      const exported = await api<Page>(
        "/helpdesk/ticket-queue/export?" + filters,
      );
      const lines = [
        [
          "ID",
          "问题",
          "状态",
          "优先级",
          "升级原因",
          "创建时间 UTC",
          "接手人",
          "演示时限",
          "截止时间 UTC",
        ],
        ...exported.items.map((ticket) => [
          ticket.id,
          ticket.subject,
          statusLabel[ticket.status] || ticket.status,
          ticket.priority,
          ticket.reason || "",
          ticket.created_at,
          ticket.assigned_agent_name || "尚未接手",
          slaLabel[ticket.sla.state] || ticket.sla.state,
          ticket.sla.due_at,
        ]),
      ];
      const url = URL.createObjectURL(
        new Blob([ticketCsv(lines)], { type: "text/csv;charset=utf-8" }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = "resolveai-tickets.csv";
      link.click();
      URL.revokeObjectURL(url);
      setMessage(
        `已导出 ${exported.items.length} / ${exported.total} 条匹配工单${exported.truncated ? "（单次最多 1000 条）" : ""}。`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "导出失败");
    }
  }
  return (
    <section className="panel">
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
      {updating && (
        <p className="panel-footnote" role="status">
          正在更新工单列表…
        </p>
      )}
      <div className="section-heading">
        <h2>
          支持工单
          <span className="small-pill">
            {filteredTickets.length} / {data?.total ?? 0}
          </span>
        </h2>
        <button
          className="text-button"
          onClick={() => setRevision((value) => value + 1)}
        >
          刷新列表
        </button>
      </div>
      <div className="ticket-filters">
        <label>
          搜索问题 / 原因 / ID
          <input
            value={ticketSearch}
            onChange={(e) => {
              setTicketSearch(e.target.value);
              setPage(1);
            }}
            placeholder="例如 VPN 或权限"
          />
        </label>
        <label>
          工单状态
          <select
            aria-label="工单状态"
            value={ticketStatus}
            onChange={(e) => {
              setTicketStatus(e.target.value);
              setPage(1);
            }}
          >
            <option value="ALL">全部状态</option>
            {Object.entries(statusLabel).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          优先级
          <select
            aria-label="优先级"
            value={ticketPriority}
            onChange={(e) => {
              setTicketPriority(e.target.value);
              setPage(1);
            }}
          >
            <option value="ALL">全部优先级</option>
            <option value="URGENT">紧急</option>
            <option value="HIGH">高</option>
            <option value="MEDIUM">普通</option>
            <option value="LOW">低</option>
          </select>
        </label>
        <label>
          处理时限
          <select
            aria-label="处理时限"
            value={ticketSla}
            onChange={(event) => {
              setTicketSla(event.target.value);
              setPage(1);
            }}
          >
            <option value="ALL">全部时限</option>
            {Object.entries(slaLabel)
              .filter(([value]) =>
                ["on_track", "due_soon", "overdue"].includes(value),
              )
              .map(([value, label]) => (
                <option value={value} key={value}>
                  {label}
                </option>
              ))}
          </select>
        </label>
        <label>
          接手范围
          <select
            aria-label="接手范围"
            value={assignment}
            onChange={(event) => {
              setAssignment(event.target.value);
              setPage(1);
            }}
          >
            <option value="all">全部工单</option>
            <option value="mine">我接手的</option>
            <option value="unassigned">尚未接手</option>
          </select>
        </label>
        <button
          className="secondary"
          disabled={loading || !data?.total || ticketSearch.trim() !== search}
          onClick={exportTickets}
        >
          <ArrowDownToLine size={15} />
          导出筛选结果
        </button>
      </div>
      <p className="panel-footnote">
        搜索、状态、优先级、接手人和时限筛选由服务端执行。导出最多 1000
        条匹配摘要，不受当前页限制。时限为演示目标。
      </p>
      {filteredTickets.length === 0 ? (
        <div className="context-empty large">
          <Ticket size={36} />
          <h3>{data?.total ? "没有匹配的工单" : "没有匹配的工单"}</h3>
          <p>
            {data?.total
              ? "调整搜索或筛选条件后重试。"
              : "需人工介入的诊断将自动出现在这里。"}
          </p>
        </div>
      ) : (
        <div className="ticket-list">
          {filteredTickets.map((t) => (
            <article className="ticket-card" key={t.id}>
              <div>
                <span className="source-code">#{t.id.slice(0, 8)}</span>
                <h3>{t.subject}</h3>
                <p>{t.reason}</p>
                <small>
                  {new Date(t.created_at).toLocaleString("zh-CN", {
                    timeZone: "Asia/Hong_Kong",
                  })}{" "}
                  · {t.priority === "HIGH" ? "高优先级" : "普通优先级"}
                </small>
                <div className="ticket-owner">
                  <span>接手人：{t.assigned_agent_name || "尚未接手"}</span>
                  <SlaBadge ticket={t} />
                </div>
              </div>
              <div className="ticket-actions">
                <span
                  className={
                    t.status === "RESOLVED" || t.status === "CLOSED"
                      ? "small-pill green"
                      : "small-pill amber"
                  }
                >
                  {statusLabel[t.status]}
                </span>
                {[
                  "OPEN",
                  "ESCALATED",
                  "CLOSED",
                  "RESOLVED",
                  "WAITING_FOR_CUSTOMER",
                ].includes(t.status) && (
                  <button
                    className="secondary"
                    disabled={ticketBusy || updating}
                    onClick={() =>
                      changeStatus(
                        t.id,
                        "IN_PROGRESS",
                        ["OPEN", "ESCALATED"].includes(t.status) &&
                          !t.assigned_agent_id,
                      )
                    }
                  >
                    {["CLOSED", "RESOLVED"].includes(t.status)
                      ? "重新处理"
                      : t.status === "WAITING_FOR_CUSTOMER"
                        ? "继续处理"
                        : "接手处理"}
                  </button>
                )}
                {t.status === "IN_PROGRESS" && (
                  <button
                    className="secondary"
                    disabled={ticketBusy || updating}
                    onClick={() => changeStatus(t.id, "RESOLVED")}
                  >
                    标记解决
                  </button>
                )}
                {t.status === "IN_PROGRESS" && (
                  <button
                    className="secondary"
                    disabled={ticketBusy || updating}
                    onClick={() => changeStatus(t.id, "WAITING_FOR_CUSTOMER")}
                  >
                    等待员工反馈
                  </button>
                )}
                {t.status === "RESOLVED" && (
                  <button
                    className="secondary"
                    disabled={ticketBusy || updating}
                    onClick={() => changeStatus(t.id, "CLOSED")}
                  >
                    关闭工单
                  </button>
                )}
              </div>
              <TicketOps ticket={t} api={api} onChanged={changed} />
            </article>
          ))}
        </div>
      )}
      <div className="pagination">
        <span>
          共 {data?.total ?? 0} 条 · 第 {page} /{" "}
          {Math.max(1, Math.ceil((data?.total || 0) / size))} 页
        </span>
        <label>
          每页数量
          <select
            aria-label="工单每页数量"
            value={size}
            onChange={(event) => {
              setSize(Number(event.target.value));
              setPage(1);
            }}
          >
            <option value={10}>10</option>
            <option value={20}>20</option>
            <option value={50}>50</option>
          </select>
        </label>
        <button
          className="secondary"
          disabled={loading || page === 1}
          onClick={() => setPage((value) => value - 1)}
        >
          上一页
        </button>
        <button
          className="secondary"
          disabled={loading || page * size >= (data?.total || 0)}
          onClick={() => setPage((value) => value + 1)}
        >
          下一页
        </button>
      </div>
    </section>
  );
}
