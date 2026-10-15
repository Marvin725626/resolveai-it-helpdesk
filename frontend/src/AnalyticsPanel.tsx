import { useEffect, useState } from "react";
import { Activity, ArrowDownToLine, Clock, Ticket } from "lucide-react";
import TeamMetricsPanel from "./TeamMetricsPanel";

type Metrics = {
  days: number;
  total_runs: number;
  completed_runs: number;
  escalated_runs: number;
  escalation_rate: number | null;
  supported_rate: number | null;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  latency_samples: number;
  generated_at: string;
  feedback: { helpful: number; unhelpful: number; responses: number };
  daily: { date: string; runs: number; escalated: number }[];
  categories: { category: string; count: number }[];
  ticket_statuses: Record<string, number>;
};
const category: Record<string, string> = {
  vpn: "VPN / 网络",
  account: "身份与权限",
  software: "办公软件",
  service: "内部服务",
  email: "企业邮箱",
  unknown: "未分类",
};
const statuses: Record<string, string> = {
  OPEN: "待处理",
  ESCALATED: "转人工",
  IN_PROGRESS: "处理中",
  RESOLVED: "已解决",
  CLOSED: "已关闭",
  WAITING_FOR_CUSTOMER: "等待反馈",
};
const percent = (value: number | null) =>
  value === null ? "—" : `${(value * 100).toFixed(1)}%`;
const latency = (value: number | null | undefined) =>
  value == null ? "—" : `${value.toFixed(1)} ms`;

export default function AnalyticsPanel({
  api,
}: {
  api: <T>(path: string) => Promise<T>;
}) {
  const [days, setDays] = useState(7);
  const [data, setData] = useState<Metrics>();
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setData(undefined);
    setError("");
    api<Metrics>(`/helpdesk/analytics?days=${days}`)
      .then((value) => {
        if (active) setData(value);
      })
      .catch((e) => {
        if (active) setError(e.message);
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
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `resolveai-metrics-${days}d.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }
  const maximum = Math.max(1, ...(data?.daily.map((day) => day.runs) || []));
  const categoryTotal = data?.completed_runs || 1;
  return (
    <div className="analytics-view">
      <div className="analytics-toolbar">
        <div>
          <h2>支持运营概览</h2>
          <p className="muted tiny">
            诊断统计来自当前账号；工单状态覆盖当前工作区全部时间。
          </p>
        </div>
        <div className="analytics-actions">
          <label>
            统计范围
            <select
              aria-label="统计范围"
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
            >
              <option value={7}>最近 7 天</option>
              <option value={30}>最近 30 天</option>
              <option value={90}>最近 90 天</option>
            </select>
          </label>
          <button
            className="secondary"
            onClick={() => setRevision((value) => value + 1)}
          >
            刷新
          </button>
          <button className="secondary" disabled={!data} onClick={download}>
            <ArrowDownToLine size={15} />
            导出指标
          </button>
        </div>
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {!data && !error && (
        <p role="status" className="muted">
          正在读取运行指标…
        </p>
      )}
      {data && (
        <>
          <div className="analytics-kpis">
            <article className="panel">
              <span>
                <Activity size={17} />
                诊断请求
              </span>
              <strong>{data.total_runs}</strong>
              <small>其中 {data.completed_runs} 次完成</small>
            </article>
            <article className="panel">
              <span>
                <Ticket size={17} />
                转人工率
              </span>
              <strong>{percent(data.escalation_rate)}</strong>
              <small>
                {data.escalated_runs} / {data.completed_runs} 次完成诊断
              </small>
            </article>
            <article className="panel">
              <span>
                <Clock size={17} />
                平均响应耗时
              </span>
              <strong>{latency(data.avg_latency_ms)}</strong>
              <small>
                P95 {latency(data.p95_latency_ms)} · {data.latency_samples}{" "}
                个样本
              </small>
            </article>
            <article className="panel">
              <span>
                <Activity size={17} />
                证据通过率
              </span>
              <strong>{percent(data.supported_rate)}</strong>
              <small>证据门控通过 / 完成诊断</small>
            </article>
          </div>
          <div className="analytics-grid">
            <section className="panel">
              <div className="section-heading">
                <h2>每日诊断量</h2>
                <span className="micro-label">香港时间 · 最近 {days} 天</span>
              </div>
              <div
                className="trend-chart"
                role="img"
                aria-label={`最近 ${days} 天的每日诊断数量，详细数据见下方表格`}
              >
                {data.daily.map((day) => (
                  <div
                    className="trend-column"
                    key={day.date}
                    title={`${day.date}：${day.runs} 次，转人工 ${day.escalated} 次`}
                  >
                    <span>{day.runs || ""}</span>
                    <div
                      className="trend-bar"
                      style={{
                        height: `${Math.max(2, (day.runs / maximum) * 130)}px`,
                      }}
                    />
                    <small>
                      {days <= 7 ? day.date.slice(5) : day.date.slice(8)}
                    </small>
                  </div>
                ))}
              </div>
              <details className="metric-table">
                <summary>查看每日数据表</summary>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>日期</th>
                        <th>诊断请求</th>
                        <th>转人工</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.daily.map((day) => (
                        <tr key={day.date}>
                          <td>{day.date}</td>
                          <td>{day.runs}</td>
                          <td>{day.escalated}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </section>
            <section className="panel">
              <div className="section-heading">
                <h2>问题分类</h2>
                <span className="micro-label">完成诊断</span>
              </div>
              {data.categories.length ? (
                data.categories.map((item) => (
                  <div className="category-meter" key={item.category}>
                    <div>
                      <span>{category[item.category] || item.category}</span>
                      <strong>{item.count}</strong>
                    </div>
                    <div className="meter-track">
                      <div
                        style={{
                          width: `${(item.count / categoryTotal) * 100}%`,
                        }}
                      />
                    </div>
                  </div>
                ))
              ) : (
                <p className="context-empty">
                  还没有完成诊断，提交一个问题后即可查看分类。
                </p>
              )}
              <p className="panel-footnote">
                证据通过率反映规则门控结果，不等于回答正确率。
              </p>
            </section>
            <section className="panel ticket-distribution">
              <div className="section-heading">
                <h2>工作区工单分布</h2>
                <span className="micro-label">全部时间</span>
              </div>
              <div>
                {Object.entries(statuses).map(([key, label]) => (
                  <article key={key}>
                    <span>{label}</span>
                    <strong>{data.ticket_statuses[key] || 0}</strong>
                  </article>
                ))}
              </div>
            </section>
            <section className="panel feedback-summary">
              <div>
                <h2>诊断反馈</h2>
                <p className="panel-footnote">
                  仅统计当前账号在所选窗口内完成诊断的最新反馈。未反馈的诊断不计入反馈数量。
                </p>
              </div>
              <span>
                有帮助 <strong>{data.feedback.helpful}</strong>
              </span>
              <span>
                仍需帮助 <strong>{data.feedback.unhelpful}</strong>
              </span>
              <span>
                总反馈 <strong>{data.feedback.responses}</strong>
              </span>
            </section>
          </div>
          <p className="panel-footnote">
            更新时间：
            {new Date(data.generated_at).toLocaleString("zh-CN", {
              timeZone: "Asia/Hong_Kong",
            })}
            。无完成诊断时比率显示 —；耗时统计仅使用有耗时的完成记录，P95
            采用最近秩法。离线演示耗时不代表真实模型表现。
          </p>
        </>
      )}
      <TeamMetricsPanel api={api} />
    </div>
  );
}
