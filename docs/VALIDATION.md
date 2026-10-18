# Local validation

Validated on 2026-10-12 in `E:\agent\resolveai`.

- Python: isolated `.venv`, versions in `backend/requirements.lock.txt`.
- Frontend: `npm run build` passes TypeScript checking and Vite production build.
- Backend: 34 ResolveAI regression tests pass using a temporary SQLite database. Database engine disposal is verified by clean test exit.
- Live API: six manually labelled scenarios run through the actual server; Recall@4 = 1.0, MRR = 1.0, escalation-decision accuracy = 1.0. This is a tiny offline smoke set, not production performance. Per-case results and actual latency are in locally generated `evaluation.local.json`.
- Browser: demo sign-in; VPN diagnosis with source `[VPN-001]`; simulated degraded service creates a ticket; UI can take and resolve the ticket; the desktop layout and 390px responsive layout render without page overflow.
- Service ports: frontend 5174 and backend 8104. Startup and stop scripts isolate processes by recorded PID and project command line.

Not validated: real provider function calling, semantic embeddings, Docker image execution, PostgreSQL pgvector integration or actual enterprise IT connectors. Docker daemon was unavailable and no model key was provided. Account and service fixtures are explicitly simulated.


## 2026-10-12 expansion verification

- Backend: `python -m pytest tests/test_resolveai.py -q` → **15 passed**. New checks cover metrics deltas, valid period bounds, authentication, empty-workspace isolation, Hong Kong midnight grouping, nearest-rank P95 and exclusion of failed runs from completed-run denominators.
- CSV: `npm run test:csv` verifies exact Unicode/quote/newline output, formula prefix neutralization and ordinary text.
- Frontend: `npm run build` passes TypeScript and production bundling.
- Live browser: sign-in; software and VPN diagnoses; automatic handoff; 7 / 30 day analytics; actual JSON and CSV downloads; combined keyword/status/priority filters; disabled export on no matches; 390px layout without document overflow; zero page exceptions.
- Screenshots are from that local browser session, not design mockups. Reproduction script: `scripts/smoke-browser.cjs`. Run it only against a development database because it creates demo runs and tickets.

This is still an offline development demonstration. Analytics values in screenshots describe development records, not real enterprise users or validated business improvements. All-time workspace ticket counts and current-user windowed run counts intentionally have different scopes, labelled in the interface.


## v1.1.0 workflow verification · 2026-10-12

- Backend: **22 passed**, including real event persistence and ordering, self-claim idempotency, redacted/idempotent notes, stale update rejection, preservation of resolution time on close, workspace isolation, deadline boundaries, late completion, persistent/revisable feedback, colleague ownership permissions and legacy-write bypass protection.
- Browser: actual sign-in and diagnoses; useful-feedback submission; self-claim; two persisted internal notes; wait/resume/resolve/close; nine resulting events; target-time filter; desktop and 390px ticket detail screenshots; JSON/CSV downloads; no uncaught page exceptions or document overflow.
- CSV formatting checks and TypeScript/Vite production build pass.
- Existing tables and the first project remain intact; startup creates only the new application-event table for local development. Historical tickets have no invented event backfill.

The operation log is application-level, not a tamper-proof audit product. Target times are explicit demo policy using calendar hours without business-hour calendars or waiting-state pauses. No background email/Slack reminders or real enterprise operations were performed.


## v1.2.0 verification · 2026-10-12

- Backend: 27 passing tests covering version conflicts, archive/restore, preserved run evidence, rollback after indexing failure, tenant/admin scope, preview without runs/tickets, knowledge export, owner-only recovery and three-minute deadline checks.
- Browser: real UTF-8 Markdown import; edit and reindex; stop retrieving archived sources; restore as a new version; actual JSON download; 390px editor without overflow.
- Recovery: intercepted and dropped the actual stream response only after the real server finished diagnosis. UI retrieved the same persisted result; ticket count increased exactly once. Reload recovered the stored pending ID without resubmitting diagnosis.
- New screenshots show actual developer sample sources and version events; repeated trial samples were archived with history preserved.

No durable graph checkpointing or production deployment claims are added. Knowledge export is not a full database backup. Existing real-model/PostgreSQL/Docker validation limitations remain.


## v1.3.0 verification · 2026-10-13

- Backend: 34 passing regressions, including 1005 isolated synthetic tickets; disjoint pages; mine/unassigned scope; literal wildcard characters; 1000-row export cap; summary-only responses; stable same-time history ordering; lazy full-result fetch; readiness without key disclosure; backup integrity and path/overwrite constraints.
- Offline evaluation: 16 / 16 labelled fixture checks passed in a disposable database; real_model_calls=false. The committed report records actual generation time, version, per-case checks and latency. CI runs the same strict evaluation.
- Browser: core diagnosis/feedback/handoff/notes/wait/resume/resolve/close; actual ticket/history pages; cross-page CSV; assignment/category filters; full result on demand; report download; readiness; 390px evaluation layout with no document overflow or uncaught page exceptions.
- Frontend: typecheck and production build; CSV formatting and formula handling; authored-module formatting. npm audit issues were remediated by a Vite patch, compatible dependency updates and removing an unnecessary affected plugin chain.

These are development fixtures and local browser operations. They do not establish real customer volume, production business impact, semantic faithfulness or verified external-model/enterprise-system integration.


## v1.4.0 verification · 2026-10-13

- Backend: **39 passed**. New coverage includes assignment/release with preserved status and deadline, redacted event data, replay without duplicate mutation (including after a later release), stale-version rejection, finished-ticket/invalid-input rejection, fresh support-user role checks, foreign workspace and inactive-target rejection.
- History: 237 synthetic notes plus the created event exist only in the disposable test database. Traversal starts with the latest 100 and prepends older cursor pages in exact sequence. Inserting a newer event after page one does not alter the older traversal; the terminal cursor and query bounds are checked.
- Browser: the core diagnosis/feedback/ticket lifecycle and paged queue/history/report suites pass. A new UI diagnosis creates a dedicated demo ticket; the administrator assigns it, the script waits for real server commit and then drops the response, and the UI retries the frozen request without creating a second event. The UI then releases the ticket while retaining its status. Desktop and 390px screenshots show actual records; no page exception or horizontal overflow was observed.
- Frontend: authored-module formatting and TypeScript/Vite production build pass. The existing page smoke now reads expected software version from package.json. Strict isolated offline evaluation is 16/16 for version 1.4.0.

The long-history fixture is backend API coverage, not a claim of 237 real staff operations. The live browser check uses the existing demonstration administrator; it does not create fictional staff members or connect to enterprise systems. New screenshots are resolveai-assignment.png and resolveai-assignment-mobile.png. Original v1.3 integration limitations remain.


## v1.5.0 verification · 2026-10-14

- Backend: **43 passed** across the existing helpdesk suite and invitation API tests. Invitation coverage includes SHA-256-only persistence, manager-only operations, fixed support-agent role, case-insensitive login, revoke, expiry, replay, cross-workspace isolation and simultaneous acceptance.
- Schema: the invitation Alembic revision adds the invitation table and case-insensitive unique email index; local bootstrap checks for the expression index explicitly because SQLite does not reflect it reliably.
- Frontend: TypeScript/Vite production build passes. The new team page and invitation acceptance page are included in authored-module formatting checks.
- Browser: isolated temporary workspace; owner created a one-time invite, a second browser context accepted it with its own credentials, the fragment was removed before follow-up requests, the new account reported `SUPPORT_AGENT`, and the owner saw it in the assignment API. The 390px team page has no document overflow. Screenshots use a disposable database and synthetic `example.com` identities; the active bearer link was removed before capture.
- Repeatable browser entry point: `scripts/smoke-invitations.cjs`; the temporary services and database used for this run were stopped and removed after verification.
- Limits: invite links are manually delivered, are not email-verified, and are bearer credentials. No email delivery or identity-provider integration is configured.

The 43 passing backend tests are isolated development regressions; they do not validate PostgreSQL concurrency, production mail delivery or external identity verification.


## v1.6.0 · 2026-10-15 · Batch integration

The following SQLite development suites were executed in separate processes and disposable databases. They cover 48 pytest tests in total, including rich lifecycle scenarios; this is a regression count, not a production success rate.

| Suite | Result |
| --- | --- |
| test_resolveai.py | 39 passed |
| test_invitations.py | 4 passed |
| test_notifications.py | 1 passed |
| test_requester_followup.py | 1 passed |
| test_attachments.py | 1 passed |
| test_resolutions.py | 1 passed |
| test_knowledge_drafts.py | 1 passed |

The legacy resolve fixtures now submit the structured resolution resource. The long-history test clears only its fixture rate-limit state, and the notification test preserves valid requester reminders while checking that self-operations add none. Production rate limits and notification behavior were retained.

Frontend authored files were formatted and the TypeScript/Vite production build passed (1917 modules). Fresh and upgraded SQLite databases reached Alembic head `53df04c2178b`; foreign-key checks passed for the three new resolution, satisfaction and knowledge-draft tables.

Resolution coverage includes current assignee/administrator permissions, CAS conflicts, repeat requests, immutable resolution rounds, requester-only per-round scoring, transaction failures and legacy confirmation without invented snapshots. Knowledge-draft coverage includes author/workspace isolation, original-create replay after editing, rejection and resubmission, source-resolution freshness, failed publication rollback and actual retrieval after publishing.

The browser reproduction entry point is `scripts/smoke-resolution-loop.cjs`. It creates random temporary example.com accounts and synthetic VPN content; no real customer input is used. Browser validation passed: two resolution rounds, requester reopen, confirmation and 5/5 score, support-authored draft, administrator rejection, author revision, administrator publication as KD-00001 v1 and actual retrieval hit. Before publication no draft hit was returned. An internal-note fixture was absent from the public resolution, draft and retrieval. The 390px requester page had no horizontal overflow and both browser contexts had zero page errors. Real LLM, PostgreSQL and production recovery remain unverified.


The managed local services were restarted after integration. Web `5174` and API `8104` returned HTTP 200; both the root API and OpenAPI reported version `1.6.0`, including the new resolution and draft routes. Existing user/database data were preserved; only the independent test services and disposable database were removed.


## v1.7.0 · 2026-10-15 · Triage and team operations

This batch executed four isolated pytest suites in separate processes: `test_resolveai.py` (39 passed), `test_notifications.py` (1 passed), `test_triage.py` (1 passed) and `test_team_metrics.py` (1 passed). These 42 tests include rich multi-step development scenarios; the older v1.6 results above remain a separate historical record. CI also retains the previous independent workflow suites.

Triage coverage includes assignee/administrator permissions, tenant isolation, request replay after later transfer/completion, CAS conflicts, transaction failure, priority deadlines derived from the original creation time, preserved assignment and redacted event reasons with fixed notification summaries. Personal views cover strict filter fields, per-user scope, persistent reads, immutable-create replay, version conflicts, a 10-active-view quota and tombstone deletion.

Team metrics use a fixed UTC clock and exact synthetic records to verify boundary inclusion, current waiting/backlog state, shared SLA cutoffs, inactive assignee workload, resolution rounds versus distinct ticket counts, an independent rating-submission window, rating distribution and null averages, tenant separation and support-role restrictions.

Authored frontend formatting and the TypeScript/Vite production build passed (1920 modules). Fresh and upgrade SQLite migrations passed at head `c7e60b9124d8`, including foreign-key checks. The isolated two-account browser workflow passed: HIGH to URGENT priority update preserved creation time and assignment, produced the original-created-plus-one-hour overdue deadline, and recorded prior/new deadlines with fixed notifications. A personal view survived reload, applied from page two back to page one and cleared a focused ticket, remained private from the other account, and disappeared after deletion/reload. The team panel switched to 30 days and its actual downloaded JSON reported days=30. The synthetic workspace snapshot contained 12 active tickets (one URGENT, eleven unassigned); these are test records, not production scale. The 390px layout had no horizontal document overflow and there were zero browser page errors.


CI generates its default fixture password randomly for each workflow run via GITHUB_ENV; no fixed reusable demo password is stored in the workflow. Fixture databases and credentials remain isolated from deployed accounts.


## v1.8.0 · 2026-10-16 · 部署与恢复演练

| 检查 | 结果 |
| --- | --- |
| 核心后端回归 `test_resolveai.py` | **39 passed**（隔离开发数据库） |
| SQLite 数据库与附件 bundle `test_recovery_bundle.py` | **1 passed**（隔离 SQLite、合成账号与附件） |
| Docker/PostgreSQL 容器集成与 `postgres-check` / `live-check` / `recreate-check` | **全部通过**：三容器健康、迁移、业务闭环、两类并发与卷持久化 |
| 宿主机 `postgres_restore_drill.py --offline-confirmed` | **通过**：新临时数据库恢复、活跃附件 SHA-256 一致、验证后清理临时库 |

恢复 bundle 演练从新目标副本登录合成账号，读取工单、通知和个人保存视图，并下载附件核对 SHA-256；还覆盖篡改数据库/附件、附件缺失、路径越界、符号链接、拒绝覆盖及源数据保持不变。它只证明隔离 SQLite 场景，不覆盖生产数据或 PostgreSQL。

Docker 部署 helper 使用独立 5184/8114 端口和独立 Compose project 配置；原本机 SQLite 5174/8104 未纳入本次部署演练。本次独立 Docker/PostgreSQL 本地实测已完成，结果不代表生产负载或真实模型验证。

实际容器验收：Python 3.12 锁定依赖镜像安装成功；前端 TypeScript/Vite 构建通过（1920 modules）；PostgreSQL 16/pgvector 的 fresh、repeat、旧版本升级保留 sentinel 数据均通过，schema head 为 `c7e60b9124d8`。真实 hybrid 查询、附件上传/下载/删除、解决记录、草稿审核发布、本人确认及评分通过；工单 revision 和个人视图 version 的并发写入均得到一个成功与一个409。隔离测试库均已清理。

部署中的同源 Nginx HTTP 验证了 SSE trace/result、离线报告及上述业务链。全部三个容器 force-recreate 后仍健康，关闭工单、5分评分、已发布知识向量行及活跃附件 SHA-256 保留。5184 返回 HTTP 200，8114 health.database 为 healthy，OpenAPI 版本1.8.0。

PostgreSQL 恢复演练短暂停止该独立部署应用，生成 custom-format dump 与1个合成活跃附件，恢复到全新 UUID 数据库和独立附件目录；关闭工单、评分、知识向量行和附件哈希匹配。演练临时数据库已删除，原数据库/附件卷未覆盖，应用恢复运行。备份与恢复报告只保留在忽略目录 `.local/`，未提交。真实模型、企业连接器及生产环境恢复仍未验证。


## v1.9.0 · 2026-10-16 · 主动报障

- 核心后端39项通过；原报障跟进、通知、附件、解决评分、分诊模块分别在独立进程通过，共44项原有回归。新增 `test_manual_requests.py` 隔离生命周期测试通过，合计45项。
- 新测试覆盖输入字段拒绝、清理后长度、凭据模式脱敏、相同请求重放与修改冲突、跨工作区拒绝访问、独立来源与描述、旧写接口阻断、公开回复、附件、解决确认和评分。手动提交不创建 AI run。
- 前端 authored formatting 检查、TypeScript 与 Vite 生产构建通过（1920 modules）；Docker 前端镜像构建通过。
- 真实 PostgreSQL 检查通过：fresh/repeat/旧版本升级保留数据、新提交记录表与新 head `d1a4f8c29b73`；两个同 ID 请求并发均成功且只产生一个工单、一个提交记录和一个客户，无孤儿记录；跨用户/租户隔离及处理后重试不重置状态通过。原向量检索、业务链和两类 CAS 检查继续通过。
- 无截图浏览器验收 `scripts/smoke-manual-requests.cjs` 使用随机新建合成工作区：服务端建单后中断首个响应，重试保持原 ID 且只有一单；实际附件上传/下载 SHA-256 相同，支持回复通知可读，用户确认关闭并评分5分，刷新后保留；390px 无横向页面溢出，0个 pageerror。

浏览器验收只允许显式开启合成写入且目标必须是 localhost/127.0.0.1。若本地未安装 Playwright，可通过 `PLAYWRIGHT_MODULE` 指定已有依赖，`CHROMIUM_PATH` 指定浏览器。设置 `RESOLVEAI_ALLOW_SYNTHETIC_WRITES=1` 后执行 `node scripts/smoke-manual-requests.cjs`；默认目标为5184，会新建合成工作区和工单，不复用现有账号，也不导出截图、密码或令牌。

- 新版同源 `live-check`、三容器 `recreate-check` 与 PostgreSQL dump/restore 演练通过，新的验证清单包含手动提交的 request/user/ticket 关联与处理中状态。恢复后 `manual_request_ownership=true`；5个合成活跃附件全部校验匹配，临时恢复库已删除，原数据库与附件卷未覆盖。
- 本机 SQLite 8104 与 Docker 8114 的 OpenAPI 均为1.9.0，均包含主动建单端点；5174与5184均返回HTTP 200。配置、合成账号及备份继续仅保存在本地忽略路径，未新增公开截图。


## v1.10.0 · 2026-10-16 · 工单检索与来源分流

- 本批相关隔离后端回归43项通过：核心39、原报障跟进1、主动报障1、分诊与保存视图1、新来源筛选1。各模块使用独立进程及临时数据库。
- 新测试覆盖主动/AI/历史三类来源、同一工单多条 Run 不重复、筛选总数与跨页 ID、导出同口径、非法来源、来源+状态组合、本人描述与 AI question、内部诊断专有词不命中、字面 `%/_`、同租户同事与跨租户隔离，以及旧视图缺省/None 创建重放和新来源视图更新。
- 前端 authored formatting、TypeScript 与生产构建通过；最终 Docker 前端构建通过（1920 modules）。既有私有配置、数据库和附件卷保留，本批没有新增数据库迁移。
- 真实 PostgreSQL `postgres-check` 通过：来源 SQL、本人描述搜索与内部上下文排除、导出条件一致、旧视图省略/None 来源重试、新视图来源保存更新；既有迁移、向量检索、完整业务链、同请求并发建单及两类 CAS 检查继续通过。仅清理自建测试数据库。
- 无截图浏览器脚本 `scripts/smoke-ticket-filters.cjs` 通过：21条合成主动报障与1条 AI 工单用于分页/组合筛选；延迟旧响应后新搜索结果保持，末尾空格与快速改回原查询不卡空，未提交报障草稿保留，新建成功清筛选并打开工单，来源视图刷新后可应用，实际 CSV 跨页导出22条匹配主动报障。队列及个人报障390px无横向页面溢出，0个 pageerror。

浏览器脚本仅允许显式设置 `RESOLVEAI_ALLOW_SYNTHETIC_WRITES=1` 且目标为 localhost/127.0.0.1，默认5184。可通过 `PLAYWRIGHT_MODULE` / `CHROMIUM_PATH` 复用本机依赖；执行 `node scripts/smoke-ticket-filters.cjs` 会创建随机合成工作区，不复用旧账号、不生成公开截图。工单查找不代表生产搜索容量或企业系统集成验收。


## v2.0.0 员工门户与目录验收 · 2026-10-16

- 后端共 **55 项**通过：39项核心回归、4项邀请检查，以及12个独立业务模块（含员工权限和服务目录）。模块分别在隔离进程/临时数据库运行。旧邀请测试原先误用本地历史测试库，现改为自身临时库，不对该库做升级式修补。
- 新员工权限检查覆盖邀请不可提权、个人统计、自有回复/附件/通知、解决确认/评分，同租户他人404和支持后台403；通用人工报障保持可用。
- 服务目录检查覆盖字段验证、发布与版本冲突、幂等提交、跨租户隔离、归档后重放、原始标签/答案快照保留。
- SQLite 旧主库只读备份副本升级通过：25张原有表摘要一致，12条原有邀请记录保留且默认SUPPORT_AGENT。实际主库在离线数据库与附件bundle保存后升级，5174/8104启动成功。
- PostgreSQL真实新库/重复迁移/旧版升级通过：升级夹具重建v1.10四值userrole枚举和无role的邀请表，再升级至`f20b8c6d4192`；并发同ID服务提交只生成一个工单与归属记录，原有分派/保存视图CAS、附件字节、pgvector检索、解决评分及知识发布通过。
- Docker在线Nginx同源API、SSE进度和打包报告通过，新增员工和目录流程通过。
- CSV、Prettier、TypeScript及Vite生产构建通过；16个隔离离线诊断样例全部通过，未调用真实模型。这是固定开发样例结果，不代表生产准确率。
- Docker容器强制重建后，员工角色、目录归档和3条修订、原始服务申请快照、评分、知识向量与附件哈希全部保留；独立新库dump/restore演练通过，6个私有附件字节一致，原库未替换，临时恢复库已删除。
- 原主动报障浏览器回归通过：响应中断后同ID重试仅一单、附件SHA-256一致、支持回复通知、确认关闭与5分评价、刷新保留、390px无溢出、零pageerror。
- 2.0新门户Playwright验收通过：随机工作区管理员UI创建发布服务、动态字段逐字输入不丢焦点、REQUESTER邀请与接受、员工专属导航、实际服务申请及UI/API快照、员工会话不调用支持后台、390px无横向溢出、零页面异常。QA图片保存在私有`.local/`，未公开上传。


## v2.1.0 目录维护闭环 · 2026-10-18

- 修复真实UI故障：目录编辑PUT只提交内容和expected_version，避免id/version/timestamps触发严格输入校验；同项保存后历史立即更新。
- 扩展隔离SQLite目录回归通过（1个综合用例）：恢复式PUT生成v4、旧修订保留、历史跨租户404/非管理员403、复制为独立v1草稿、旧申请快照不变。
- 新浏览器脚本 `scripts/smoke-catalog-maintenance.cjs` 通过：真实编辑保存并核验请求字段、可读历史、归档状态下恢复历史再保存、旧工单快照不变、另一管理员更新后的409和输入保留、刷新明确放弃/保留、独立复制草稿、后端提交后中断响应再同ID重试仅创建一项。
- 历史响应延迟并快速切换服务后，新项历史不被覆盖；模拟503后点击重试历史成功。管理员390px布局无横向溢出，零pageerror；本地QA截图已视觉检查，未公开上传。
- 原2.0员工门户浏览器回归通过：管理员创建发布、员工邀请/接受与申请、角色导航和API范围、实际快照、390px布局、零pageerror。
- Prettier、TypeScript及Vite生产构建通过。本批没有数据库结构和诊断工作流变更，未重复执行上一批全量PostgreSQL恢复及模型评估；既有2.0记录不作为本批新增执行结果。
