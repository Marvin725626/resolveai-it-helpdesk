export type ServiceSnapshot = {
  item_id: string;
  code: string;
  title: string;
  version: number;
  fields: { key: string; label: string; answer: string }[];
};

export default function ServiceRequestSnapshot({
  data,
}: {
  data: ServiceSnapshot;
}) {
  return (
    <section
      className="manual-request-detail service-request-snapshot"
      aria-label="服务申请快照"
    >
      <h3>服务申请 · {data.title}</h3>
      <p className="panel-footnote">
        提交版本 v{data.version} · {data.code}
      </p>
      <dl>
        {data.fields.map((field) => (
          <div key={field.key}>
            <dt>{field.label}</dt>
            <dd>{field.answer || "未填写"}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
