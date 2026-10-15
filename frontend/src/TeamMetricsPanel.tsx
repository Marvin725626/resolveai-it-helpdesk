import { useEffect, useRef, useState } from "react";
import { ArrowDownToLine, RefreshCw, Users } from "lucide-react";

type TeamMetrics = {
  scope: "current_workspace";
  timezone: "UTC";
  days: number;
  as_of: string;
  snapshot: {
    current_backlog: number;
    statuses: Record<string, number>;
    priorities: Record<string, number>;
    unassigned: number;
    due_soon: number;
    overdue: number;
    active_workload: {
      assignee_id: string | null;
      assignee_name: string;
      count: number;
    }[];
  };
  resolution_window: {
    from: string;
    to: string;
    basis: string;
    rounds: number;
    distinct_resolved_tickets: number;
    categories: Record<string, number>;
  };
  rating_window: {
    from: string;
    to: string;
    basis: string;
    rating_count: number;
    average_rating: number | null;
    distribution: Record<string, number>;
  };
  definitions: Record<string, string>;
};
type Api = <T>(path: string) => Promise<T>;
const statusNames: Record<string, string> = {
  OPEN: "待处理",
  ESCALATED: "转人工",
  IN_PROGRESS: "处理中",
  WAITING_FOR_CUSTOMER: "等待反馈",
  RESOLVED: "已解决",
  CLOSED: "已关闭",
};
const priorityNames: Record<string, string> = {
  URGENT: "紧急",
  HIGH: "高",
  MEDIUM: "中",
  LOW: "低",
};
const categoryNames: Record<string, string> = {
  configuration: "配置",
  account_access: "账号权限",
  software: "软件",
  service: "服务",
  guidance: "操作指导",
  other: "其他",
};
const localTime = (value: string) =>
  new Date(value).toLocaleString("zh-HK", { timeZone: "Asia/Hong_Kong" });

export default function TeamMetricsPanel({ api }: { api: Api }) {
  const [days, setDays] = useState(7);
  const [data, setData] = useState<TeamMetrics>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const apiRef = useRef(api);
  apiRef.current = api;
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    setData(undefined);
    apiRef
      .current<TeamMetrics>(`/helpdesk/team-metrics?days=${days}`)
      .then((result) => {
        if (active) setData(result);
      })
      .catch((e) => {
        if (active)
          setError(e instanceof Error ? e.message : "团队指标载入失败");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [days, revision]);
  function download() {
    if (!data) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `resolveai-team-metrics-${data.days}d.json`;
    link.click();
    URL.revokeObjectURL(url);
  }
  return (
    <section
      className="team-metrics-panel panel"
      aria-labelledby="team-metrics-heading"
    >
      <div className="section-heading">
        <div>
          <h2 id="team-metrics-heading">
            <Users size={18} />
            团队运营指标
          </h2>
          <p className="panel-footnote">
            工作区工单与评分数据；与上方当前账号的AI诊断指标分开统计。
          </p>
        </div>
        <div className="team-metrics-toolbar">
          <label>
            滚动窗口
            <select
              aria-label="团队指标统计窗口"
              value={days}
              onChange={(event) => setDays(Number(event.target.value))}
            >
              <option value={7}>最近7天</option>
              <option value={30}>最近30天</option>
              <option value={90}>最近90天</option>
            </select>
          </label>
          <button
            className="secondary"
            disabled={loading}
            onClick={() => setRevision((value) => value + 1)}
          >
            <RefreshCw size={14} />
            刷新
          </button>
          <button
            className="secondary"
            disabled={loading || !!error || !data}
            onClick={download}
          >
            <ArrowDownToLine size={14} />
            导出JSON
          </button>
        </div>
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {loading && (
        <p className="muted" role="status">
          正在读取团队指标…
        </p>
      )}
      {data && (
        <>
          <p className="panel-footnote">
            当前积压和工作量为全时间实时快照，不受窗口筛选影响。解决轮次按解决时间统计，评分按评分提交时间统计；UTC滚动窗口：
            {localTime(data.resolution_window.from)} 至 {localTime(data.as_of)}
            （香港时间显示）。
          </p>
          <div className="team-metrics-cards">
            <article className="team-metric-card">
              <span>当前积压</span>
              <strong>{data.snapshot.current_backlog}</strong>
              <small>未解决及等待反馈工单</small>
            </article>
            <article className="team-metric-card">
              <span>未分派</span>
              <strong>{data.snapshot.unassigned}</strong>
              <small>当前积压</small>
            </article>
            <article className="team-metric-card">
              <span>即将超时</span>
              <strong>{data.snapshot.due_soon}</strong>
              <small>沿用队列SLA规则</small>
            </article>
            <article className="team-metric-card">
              <span>已超时</span>
              <strong>{data.snapshot.overdue}</strong>
              <small>沿用队列SLA规则</small>
            </article>
            <article className="team-metric-card">
              <span>解决轮次</span>
              <strong>{data.resolution_window.rounds}</strong>
              <small>
                涉及 {data.resolution_window.distinct_resolved_tickets}{" "}
                张去重工单
              </small>
            </article>
            <article className="team-metric-card">
              <span>工单评分</span>
              <strong>
                {data.rating_window.average_rating == null
                  ? "—"
                  : data.rating_window.average_rating.toFixed(2)}
              </strong>
              <small>{data.rating_window.rating_count} 条评分</small>
            </article>
          </div>
          <div className="team-metrics-table-wrap">
            <section>
              <h3>当前工单状态</h3>
              <table>
                <thead>
                  <tr>
                    <th>状态</th>
                    <th>数量</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.snapshot.statuses).map(
                    ([key, count]) => (
                      <tr key={key}>
                        <td>{statusNames[key] || key}</td>
                        <td>{count}</td>
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
            </section>
            <section>
              <h3>当前积压优先级</h3>
              <table>
                <thead>
                  <tr>
                    <th>优先级</th>
                    <th>数量</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.snapshot.priorities).map(
                    ([key, count]) => (
                      <tr key={key}>
                        <td>{priorityNames[key] || key}</td>
                        <td>{count}</td>
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
            </section>
            <section className="team-workload-table">
              <h3>当前接手工作量</h3>
              <p className="panel-footnote">包含仍负责未完成工单的历史成员。</p>
              <table>
                <thead>
                  <tr>
                    <th>接手人</th>
                    <th>未完成工单</th>
                  </tr>
                </thead>
                <tbody>
                  {data.snapshot.active_workload.map((row) => (
                    <tr key={row.assignee_id || "unassigned"}>
                      <td>{row.assignee_name}</td>
                      <td>{row.count}</td>
                    </tr>
                  ))}
                  {!data.snapshot.active_workload.length && (
                    <tr>
                      <td colSpan={2}>当前无积压工单</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </section>
            <section>
              <h3>窗口内解决分类</h3>
              <table>
                <thead>
                  <tr>
                    <th>分类</th>
                    <th>解决轮次</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.resolution_window.categories).map(
                    ([key, count]) => (
                      <tr key={key}>
                        <td>{categoryNames[key] || key}</td>
                        <td>{count}</td>
                      </tr>
                    ),
                  )}
                  {!Object.keys(data.resolution_window.categories).length && (
                    <tr>
                      <td colSpan={2}>暂无解决记录</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </section>
            <section className="team-metric-distribution">
              <h3>评分分布</h3>
              <table>
                <thead>
                  <tr>
                    <th>评分</th>
                    <th>数量</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.rating_window.distribution).map(
                    ([score, count]) => (
                      <tr key={score}>
                        <td>{score}分</td>
                        <td>{count}</td>
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
            </section>
          </div>
          <p className="panel-footnote">
            统计时点：{localTime(data.as_of)}
            。解决轮次可能包含同一工单重开后的再次解决；不按当前接手人归算历史绩效。评分均值无样本时显示
            —。
          </p>
        </>
      )}
    </section>
  );
}
