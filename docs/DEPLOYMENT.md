# 本地 Docker 部署与恢复演练

本文说明 ResolveAI 的独立 PostgreSQL / Docker 演示部署。该编排用于本地功能与恢复演练，不是生产部署、生产切换或高可用方案。当前 Docker/PostgreSQL 实测状态记录在[验证记录](VALIDATION.md)。

## 前置条件与隔离

需要 Python 3.12、已启动的 Docker Desktop / Docker Engine 和 Docker Compose v2。示例命令使用仓库根目录的 `.venv`，但这些部署 helper 仅依赖 Python 标准库。现有 SQLite 开发服务使用 Web `5174`、API `8104`；Docker 编排默认使用 Web `5184`、API `8114`，并在回环地址监听。Docker 数据放在独立命名卷中，不会迁移、覆盖或删除 SQLite 数据。

## 初始化和启动

在 PowerShell 中从项目根目录运行：

```powershell
cd E:\agent\resolveai
.\.venv\Scripts\python.exe scripts\docker_deploy.py up
```

首次 `up` 会调用 `scripts/docker_init.py`，在 `.local/docker/.env` 创建一次性本地随机 `POSTGRES_PASSWORD`、`AUTH_SECRET` 和 `IT_DEMO_PASSWORD`，并设置 Compose project 与端口。凭据不会输出；已有配置不会被覆盖或重新生成。请将该私有配置与相应数据备份一并保管，不要提交或分享它。若要自定义 project 名或端口，可在首次初始化时运行：

```powershell
.\.venv\Scripts\python.exe scripts\docker_init.py --project resolveai-local --api-port 8114 --web-port 5184
```

启动成功后打开 `http://127.0.0.1:5184`；API 文档位于 `http://127.0.0.1:8114/docs`。运行状态与停止本地 Compose 服务：

```powershell
.\.venv\Scripts\python.exe scripts\docker_deploy.py status
.\.venv\Scripts\python.exe scripts\docker_deploy.py stop
```

`stop` 只停止当前 project 的容器，不删除命名卷。再次执行 `up` 会构建并启动该 project，保留数据库与附件卷。不要用 `docker compose down -v` 清理演示数据。

## 检查路径

```powershell
.\.venv\Scripts\python.exe scripts\docker_deploy.py postgres-check
.\.venv\Scripts\python.exe scripts\docker_deploy.py live-check
.\.venv\Scripts\python.exe scripts\docker_deploy.py recreate-check
```

`postgres-check` 在隔离数据库上检查 PostgreSQL 初始化、重复初始化与升级路径。`live-check` 在此本地 Docker 数据库写入合成验收记录，并私下保存 `.local/docker/deployment-fixture.json`。`recreate-check` 需要先运行 `live-check`，强制重建本 project 的三个容器（PostgreSQL、backend、frontend），但保留命名数据卷，然后核对合成数据仍可读；它不执行镜像构建。可能有短暂服务中断。不要对真实客户数据执行这些合成写入检查。

### 镜像拉取受限时

如果 Docker Hub 的镜像拉取失败，可从 Google 镜像缓存逐个拉取并标记为 Compose 使用的官方名称，再运行 `up`。这只改变本机已有镜像，不修改 Compose 文件或 Docker 全局镜像源：

```powershell
docker pull mirror.gcr.io/pgvector/pgvector:pg16
docker tag mirror.gcr.io/pgvector/pgvector:pg16 pgvector/pgvector:pg16
docker pull mirror.gcr.io/library/python:3.12-slim
docker tag mirror.gcr.io/library/python:3.12-slim python:3.12-slim
docker pull mirror.gcr.io/library/node:22-alpine
docker tag mirror.gcr.io/library/node:22-alpine node:22-alpine
docker pull mirror.gcr.io/library/nginx:alpine
docker tag mirror.gcr.io/library/nginx:alpine nginx:alpine
```

确认 `docker images` 中存在对应目标 tag 后重试部署。镜像源可能未缓存某个镜像或版本；此方法不绕过不可用镜像，也不改变来源版本。

## PostgreSQL dump/restore 演练

此脚本使用已经完成 `live-check` 的合成 fixture；从宿主机项目虚拟环境运行，而不是在容器中运行。`--offline-confirmed` 确认操作者已安排该本地应用写入方短暂停止：脚本会停止此 Compose project 的 frontend/backend，PostgreSQL 容器继续运行。它将数据库 dump 和活跃附件复制到新的私有 `.local/backups/pg-<随机ID>`，恢复到新的 UUID 临时数据库并核验，再删除自己创建的临时数据库并恢复应用容器。原数据库和附件卷不会被替换或删除。

```powershell
cd E:\agent\resolveai
.\.venv\Scripts\python.exe scripts\postgres_restore_drill.py --offline-confirmed
```

这是一项合成数据可恢复性演练，不是将备份切换到现有数据库的工具，也不证明生产环境恢复时间或完整性。若演练中断，先用 `scripts/docker_deploy.py status` 检查本 project 状态，再按运维流程处理；不要手动删除不确定归属的目录或数据库。

## SQLite 数据库与私有附件

`scripts/recovery_bundle.py` 的 `backup` 使用 SQLite backup API，并校验数据库完整性、外键及数据库中活跃附件的 UUID 路径、大小和 SHA-256。它仅复制活跃附件；已删除附件的 tombstone 不要求磁盘文件仍存在。manifest 记录数据库和附件的校验元数据，不额外导出运行配置；数据库与附件本身可能包含账号哈希、工单与内部资料，必须按敏感备份保管。

这是离线多文件备份：先停止所有可能写入 SQLite 或附件目录的应用进程，再显式确认：

```powershell
.\.venv\Scripts\python.exe scripts\recovery_bundle.py backup --offline-confirmed
```

默认 bundle 保存在 `.local/backups/`。恢复前会校验 manifest 白名单、SQLite 完整性与外键、数据库哈希、活跃附件哈希和大小。恢复只允许写入不存在的 `.local/restores/<新目录名>`；拒绝覆盖已有目标、现有数据库或附件。恢复后如需运行应用，应使用独立隔离配置验证，不要把其内容复制到现有数据目录。

```powershell
.\.venv\Scripts\python.exe scripts\recovery_bundle.py restore --bundle .local\backups\<bundle目录> --destination .local\restores\<新目录名>
```

SQLite backup bundle 与 `scripts/backup_sqlite.py` 的在线数据库快照用途不同。后者只备份数据库文件，不包括附件，也不代表数据库与文件系统的一致性快照。两者均不自动停止服务、上传备份或覆盖现有数据。PostgreSQL 使用上述独立 Compose 演练流程；SQLite bundle 不支持 PostgreSQL。

更多日常维护边界见[运维与备份](OPERATIONS.md)，目前各项实测结果见[验证记录](VALIDATION.md)。


## 升级到 2.0

先停止旧应用写入并保存数据库、私有附件和配置。Windows 本地部署运行 `stop.ps1`，使用 `scripts/recovery_bundle.py backup --offline-confirmed` 保存 SQLite 和附件，再运行 `start.ps1`。启动脚本先执行 Alembic 升级，成功后启动应用；不要只对旧库调用 create_all。当前迁移 head 为 `f20b8c6d4192`。旧用户角色保留，旧邀请默认 SUPPORT_AGENT；新增员工账号必须由管理员以 REQUESTER 角色邀请。Docker 使用原私有配置运行 `scripts/docker_deploy.py up`，保留现有卷并在启动前迁移。

PostgreSQL 使用独立 autocommit 迁移添加 REQUESTER 枚举值，以保证后续事务可以使用该值。存在员工用户或员工邀请时，角色迁移拒绝降级；请使用备份和完整应用版本恢复策略。服务目录迁移降级会删除目录与修订表，不用于日常回退。参见 [PostgreSQL ALTER TYPE](https://www.postgresql.org/docs/16/sql-altertype.html) 与 [Alembic autocommit_block](https://alembic.sqlalchemy.org/en/latest/api/runtime.html#alembic.runtime.migration.MigrationContext.autocommit_block)。
