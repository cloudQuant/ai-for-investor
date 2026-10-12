# 迭代 202 部署、迁移与恢复说明

本页描述本轮实现的操作顺序。实际验收状态见 [执行台账](EXECUTION_STATUS.md) 与 [验收矩阵](ACCEPTANCE.md)；示例命令不表示已经发布。操作在仓库根目录执行，使用具体部署的 env 文件、Compose project 和备份文件，不能把验收用的一次性数据库地址带入正式部署。

## 启动与迁移

开发环境的默认数据库是 PostgreSQL，开发锁包含 `asyncpg`。开发镜像通过锁文件安装依赖，入口使用配置中的 SQLAlchemy 异步 URL 执行数据库探测；缺少驱动直接报错，连接尚未就绪才重试。`migrate` 服务在数据库健康后运行一次 `alembic upgrade head`，成功后才启动 backend。

开发镜像和开发 Compose 的健康检查启动宽限期为 180 秒，宽限期后仍按失败阈值判定。该值最初依据约 171 秒的冷导入观测设置；主审前两轮 fresh up 超时失败，第三轮最终镜像从空数据库启动后在 205.189 秒内通过 Compose 等待，独立容器 HTTP 与数据库健康；完整记录见 [AC-D12 收据](evidence/2026-10-12/d12-fresh-start-parent-review.json)。它不改变沙箱执行、任务取消或业务请求超时。开发日志写入 `/var/log/ai-for-investor`，避免 DEBUG 日志在源码挂载及 reload 观察目录内持续触发文件变化记录。开发锁不包含 `mysql` extra；需要 MySQL 的部署应使用包含该驱动的生产锁，隔离测试则显式记录额外驱动版本。

开发、生产和 local Compose 的 backend 均启用 `init: true`，由 Docker init 回收退出的孤儿后代。生产入口通过 `exec gunicorn` 让信号直接传给 Gunicorn 主进程。最终镜像已独立验证 PID 1 init、一个 master 和两个 worker；受限账户无 DDL 权限时正常启动、HTTP 200，TERM 后两个 worker 完成 shutdown/finished，master 退出，容器 exit 0、OOM=false，前后 schema 指纹一致。详见[实际容器组合收据](evidence/2026-10-12/prod-runtime-parent/parent-review.json)，其中保留早期 harness 失败。验收 fixture 使用 internal 网络，只证明容器间访问，未验收宿主端口发布。

生产环境采用相同的先迁移、后启动顺序。backend 的 `DB_AUTO_CREATE_SCHEMA=false` 和 `DB_AUTO_CREATE_DEFAULT_ADMIN=false` 明确关闭启动时自动建表、补字段和创建管理员；启动读取 `alembic_version`，要求与打包的 Alembic head 完全一致。未版本化、落后或不同的 revision 均应阻止启动。

```bash
docker compose --project-directory . --env-file src/backend/.env \
  -f docker/docker-compose.yml -f docker/compose/prod.yml \
  run --rm migrate

docker compose --project-directory . --env-file src/backend/.env \
  -f docker/docker-compose.yml -f docker/compose/prod.yml \
  up -d backend frontend
```

迁移任务需要相应 DDL 权限。双 worker 无 DDL 启动用例另用受限数据库账号验证；默认 Compose 不会自动为部署创建一套独立的迁移账号。已有历史 MySQL 迁移的维护窗口确认要求继续有效，不能仅为让迁移通过而在运行中的部署设置确认变量。

普通旧库通过本轮 objective/direction 迁移保留已有任务行；没有目标的历史任务保持空目标，应用最优结果时需要明确选择结果。ORM 建表形成的已有列必须通过兼容性校验，不能默默接受不兼容列结构。

## 管理员初始化

迁移成功后，由明确的一次性操作读取 `ADMIN_USERNAME`、`ADMIN_PASSWORD`、`ADMIN_EMAIL` 并创建管理员。应用 worker 不再执行此操作。

```bash
ENV_FILE_RELATIVE_PATH=src/backend/.env \
  bash scripts/ops/docker_bootstrap_admin.sh
```

如使用自定义部署，脚本同时接受 `COMPOSE_BASE_FILE`、`COMPOSE_FILE`、`COMPOSE_PROJECT_NAME`。先确认这些变量与目标部署相同。管理员初始化会先检查数据库 revision。

## MySQL 备份与恢复

升级前执行备份脚本，保存 `.sql.gz` 与同目录 `.sha256`；脚本拒绝覆盖已有文件，使用事务一致性导出，并验证 gzip。备份目录和文件按脚本设置受限权限。

```bash
bash scripts/ops/docker_mysql_backup.sh runtime/backups/pre-upgrade.sql.gz
```

恢复前停止该 Compose project 的 backend、frontend 和 migrate，保留 MySQL 服务运行。恢复脚本检查显式破坏性操作开关、校验和、dump 中数据库名及容器 `MYSQL_DATABASE` 与 env `DB_NAME` 的一致性，之后替换目标库。

```bash
docker compose --project-directory . --env-file src/backend/.env \
  -f docker/docker-compose.yml -f docker/compose/prod.yml \
  stop backend frontend migrate

RESTORE_ALLOW_DESTRUCTIVE=YES \
  bash scripts/ops/docker_mysql_restore.sh runtime/backups/pre-upgrade.sql.gz
```

恢复后先检查数据库 revision 和关键业务行，再启动与该 revision 兼容的应用版本。不能把恢复旧库后当前新镜像拒绝启动误判为恢复失败；应按部署回退决定选择应用版本。本轮恢复脚本和恢复演练面向 MySQL；PostgreSQL 迁移验收不等同于 PostgreSQL 备份恢复验收。

## HTTP 引导与 TLS

`SERVER_DOMAIN` 是 Nginx 和证书申请共同使用的域名，`CERT_NAME` 是证书 lineage 名称，`TLS_ENABLED` 为 `true` 或 `false`。无匹配有效证书时，Nginx 可先提供 HTTP 与 HTTP-01 challenge；IP/localhost 模式明确保持 HTTP。

准备域名、证书邮箱与部署 env 后运行：

```bash
bash scripts/ops/certbot-init.sh
```

脚本备份既有证书 lineage，执行真实 ACME 申请，校验域名、有效期及公私钥匹配，通过 Nginx 配置检查和 reload 后启用 TLS。签发或激活失败时恢复原证书及 TLS 设置，失败状态不伪装为成功。生产 frontend runtime 包含执行这些校验所需的 OpenSSL CLI。

自动续期容器定期运行 Certbot；Nginx 观察证书变更并在校验通过后 reload。手工检查入口是 `scripts/ops/certbot-renew.sh`，失败时返回非零并保留原有服务状态。自定义 ACME 目录使用 `ACME_DIRECTORY_URL`；本轮证据来自隔离的本地 Pebble HTTP-01，未对用户域名或生产 CA 申请证书。

## 本轮验证边界

- 数据库测试仅操作明确命名、位于 loopback 的一次性 MySQL 8 / PostgreSQL 16 数据库。
- 镜像构建若使用临时本地 Backtrader Git mirror，必须保存原 URL、精确 commit/tree 与镜像标识；这是固定源码的构建证据，不代表 GitHub 网络链路已通过。
- 浏览器样式测试覆盖当前 Playwright Chromium、Firefox、WebKit；Tailwind 4 最低支持版本 Safari 16.4 / Chrome 111 / Firefox 128 未实机运行。
- D04/D05 的 THS dry-run 和历史补缺继续随 OpenData 接入处理，不纳入本轮部署验收。
