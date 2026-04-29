# ai-for-investor 软件需求规格说明书 SRS

版本：v0.2  
日期：2026-04-30  
状态：MVP 研发输入版  
关联文档：`01-业务需求文档BRD.md`、`02-产品需求文档PRD.md`、`04-技术设计文档.md`、`07-论坛UI设计规范与主题系统.md`

---

## 1. 文档目的

本文档将产品需求转换为可开发、可测试、可验收的软件需求规格，作为前端、后端、测试、运维协作的基线。

本文档重点定义：

1. 功能性需求。
2. 非功能性需求。
3. 权限和状态规则。
4. 外部接口和数据约束。
5. 需求追踪和验收映射。

---

## 2. 系统范围

### 2.1 系统内范围

1. 用户注册、邮箱验证、登录、退出、重置密码。
2. 角色和权限控制。
3. 博客前台展示和后台 CMS。
4. 论坛发帖、回复、举报和管理。
5. 工具列表、工具详情、受限工具任务和使用记录。
6. GitHub 项目采集、评分、审核和周报素材池。
7. 管理后台。
8. 基础埋点、指标看板、日志、审计。
9. SEO、RSS、sitemap、结构化数据。
10. 论坛统一 UI 设计系统和多主题切换。

### 2.2 系统外范围

1. 真实资金交易。
2. 券商或交易所账户绑定。
3. 用户上传任意代码执行。
4. 投资建议或收益承诺。
5. 复杂个性化推荐算法。
6. 商业支付、会员和企业私有部署。

---

## 3. 总体架构需求

| 编号 | 需求 | 优先级 |
|---|---|---|
| NFR-ARCH-001 | MVP 采用模块化单体后端架构，按 Auth、Blog、Forum、Tools、Discovery、Admin 分模块 | P0 |
| NFR-ARCH-002 | 邮件、GitHub 采集、工具任务、周报生成必须走异步 Worker | P0 |
| NFR-ARCH-003 | 前后端通过 REST API 通信，后端输出 OpenAPI 文档 | P0 |
| NFR-ARCH-004 | MySQL 存储核心关系型业务数据，MongoDB 存储项目快照和工具非结构化结果 | P0 |
| NFR-ARCH-005 | Redis 用于缓存、限流、任务状态和队列依赖 | P0 |
| NFR-ARCH-006 | 系统必须支持开发、测试、生产环境配置隔离 | P0 |
| NFR-ARCH-007 | 前端必须通过设计 token 和主题 provider 实现 UI 主题，不允许组件硬编码主题色 | P0 |

---

## 4. 功能需求

### 4.1 用户与认证

| 编号 | 需求 | 输入 | 输出/结果 | 优先级 |
|---|---|---|---|---|
| FR-AUTH-001 | 用户注册 | email、password、username | 创建 pending/active 用户并发送验证邮件 | P0 |
| FR-AUTH-002 | 邮箱验证 | verification token | 设置 `email_verified_at`，激活账号 | P0 |
| FR-AUTH-003 | 用户登录 | email、password | 返回登录态或 token | P0 |
| FR-AUTH-004 | 用户退出 | 当前登录态 | 清除登录态或使 token 失效 | P0 |
| FR-AUTH-005 | 忘记密码 | email | 发送重置密码邮件 | P0 |
| FR-AUTH-006 | 重置密码 | reset token、new password | 更新密码哈希 | P0 |
| FR-AUTH-007 | 当前用户 | 登录态 | 返回用户资料和角色 | P0 |
| FR-AUTH-008 | 更新用户资料 | 登录态、username 等可修改字段 | 资料更新成功 | P0 |
| FR-AUTH-009 | 权限校验 | user、role、resource | 允许或拒绝访问 | P0 |

认证约束：

1. 密码必须使用 Argon2 或 bcrypt 哈希存储。
2. 邮箱验证 token 必须有过期时间。
3. 注册、登录、发送邮件、重置密码必须限流。
4. 管理员操作必须记录审计日志。

### 4.2 博客

| 编号 | 需求 | 说明 | 优先级 |
|---|---|---|---|
| FR-BLOG-001 | 公开文章列表 | 支持分页、分类、标签、关键词搜索 | P0 |
| FR-BLOG-002 | 公开文章详情 | 只展示 published 状态文章 | P0 |
| FR-BLOG-003 | 创建文章 | 作者/管理员可创建 draft 文章 | P0 |
| FR-BLOG-004 | 编辑文章 | 作者/管理员可编辑有权限文章 | P0 |
| FR-BLOG-005 | 发布文章 | draft/review 可转 published | P0 |
| FR-BLOG-006 | 下线文章 | published 可转 archived | P0 |
| FR-BLOG-007 | Markdown 渲染 | 支持代码高亮并防 XSS | P0 |
| FR-BLOG-008 | SEO 输出 | 文章详情输出 canonical、meta、OG、JSON-LD | P0 |
| FR-BLOG-009 | 关联讨论帖 | 文章可关联论坛帖子 | P1 |

文章状态：

```text
draft -> review -> published -> archived
```

### 4.3 论坛

| 编号 | 需求 | 说明 | 优先级 |
|---|---|---|---|
| FR-FORUM-001 | 帖子列表 | 支持分类、标签、搜索、分页、置顶排序 | P0 |
| FR-FORUM-002 | 帖子详情 | 展示正文和一级回复 | P0 |
| FR-FORUM-003 | 发帖 | 邮箱已验证用户可发帖 | P0 |
| FR-FORUM-004 | 回复 | 邮箱已验证用户可回复未锁定帖子 | P0 |
| FR-FORUM-005 | 编辑帖子/回复 | 作者、版主、管理员可按权限编辑 | P0 |
| FR-FORUM-006 | 删除帖子/回复 | 采用软删除或隐藏 | P0 |
| FR-FORUM-007 | 举报 | 登录用户可举报帖子/回复 | P0 |
| FR-FORUM-008 | 管理操作 | 置顶、加精、锁定、隐藏 | P0 |
| FR-FORUM-009 | 反垃圾 | 新用户冷却期、频率限制、重复内容检测 | P0 |
| FR-FORUM-010 | 论坛 UI 一致性 | 列表、详情、发帖、回复、举报、管理组件遵循统一设计规范 | P0 |
| FR-FORUM-011 | 主题切换 | 游客和登录用户可切换预设主题 | P0 |
| FR-FORUM-012 | 主题偏好持久化 | 未登录用户保存到本地和 cookie；登录用户保存到用户偏好 | P0 |
| FR-FORUM-013 | 主题无侵入 | 主题切换不改变论坛权限、信息结构、路由和核心交互 | P0 |

帖子状态：

```text
normal -> hidden -> deleted
normal -> locked
```

### 4.4 工具区

| 编号 | 需求 | 说明 | 优先级 |
|---|---|---|---|
| FR-TOOL-001 | 工具列表 | 展示工具名称、类型、风险等级、运行方式 | P0 |
| FR-TOOL-002 | 工具详情 | 展示来源项目、许可证、说明、参数、限制、免责声明 | P0 |
| FR-TOOL-003 | 创建工具任务 | 邮箱已验证用户基于白名单参数创建任务 | P0 |
| FR-TOOL-004 | 查询任务状态 | 任务所有者或管理员可查看 | P0 |
| FR-TOOL-005 | 查看任务结果 | 只允许任务所有者或管理员查看 | P0 |
| FR-TOOL-006 | 工具管理 | 管理员可创建、编辑、上线、下线工具 | P0 |
| FR-TOOL-007 | 工具 manifest 校验 | 校验镜像、入口命令、参数 schema、资源上限、网络策略 | P0 |
| FR-TOOL-008 | 工具审计 | 记录创建、执行、失败、超时、下线日志 | P0 |

工具任务状态：

```text
queued -> running -> succeeded
queued -> running -> failed
queued -> running -> timeout
queued -> cancelled
```

工具安全约束：

1. 不允许用户上传任意代码。
2. 工具参数必须通过 schema 校验。
3. 工具任务必须有 CPU、内存、运行时间和输出大小限制。
4. 高风险工具不能配置为在线运行。
5. 工具运行结果必须做敏感信息过滤。

### 4.5 GitHub 项目发现

| 编号 | 需求 | 说明 | 优先级 |
|---|---|---|---|
| FR-DISC-001 | 关键词配置 | 管理员配置采集关键词 | P0 |
| FR-DISC-002 | GitHub 采集 | 调用 GitHub API 搜索项目 | P0 |
| FR-DISC-003 | 去重和快照 | 按 repo_full_name 去重并保存历史快照 | P0 |
| FR-DISC-004 | 自动评分 | 基于相关性、活跃度、影响力、可复现性、安全性评分 | P0 |
| FR-DISC-005 | 人工审核 | 编辑修改评分和状态 | P0 |
| FR-DISC-006 | 周报素材池 | 选中项目进入周报素材池 | P0 |
| FR-DISC-007 | 项目库公开页 | 展示精选项目 | P0 |
| FR-DISC-008 | 项目推荐提交 | 登录用户提交项目推荐 | P1 |

采集任务要求：

1. 支持 GitHub token 配置。
2. 支持速率限制处理。
3. 支持失败重试。
4. 支持断点续跑。
5. 记录 license、README 摘要、默认分支、最近提交、release、依赖文件。

### 4.6 管理后台

| 编号 | 需求 | 说明 | 优先级 |
|---|---|---|---|
| FR-ADMIN-001 | 用户管理 | 查看、禁用、启用用户，分配角色 | P0 |
| FR-ADMIN-002 | 文章管理 | 创建、编辑、发布、下线文章 | P0 |
| FR-ADMIN-003 | 论坛管理 | 管理帖子、回复、举报 | P0 |
| FR-ADMIN-004 | 工具管理 | 配置工具、manifest、风险等级、上线状态 | P0 |
| FR-ADMIN-005 | 项目发现管理 | 管理采集任务、项目评分和周报素材池 | P0 |
| FR-ADMIN-006 | 指标总览 | 查看内容、注册、工具和运营指标 | P0 |
| FR-ADMIN-007 | 审计日志 | 查看关键后台操作 | P0 |

---

## 5. 非功能需求

### 5.1 安全

| 编号 | 需求 | 优先级 |
|---|---|---|
| NFR-SEC-001 | 所有写接口必须校验认证和权限 | P0 |
| NFR-SEC-002 | Markdown 渲染必须防 XSS | P0 |
| NFR-SEC-003 | 管理后台接口必须二次角色校验 | P0 |
| NFR-SEC-004 | 登录、注册、发帖、工具任务创建必须限流 | P0 |
| NFR-SEC-005 | 密钥、token、数据库连接不得进入 Git | P0 |
| NFR-SEC-006 | 文件上传必须限制类型、大小和访问路径 | P0 |
| NFR-SEC-007 | 工具运行必须隔离、限制资源、记录审计 | P0 |
| NFR-SEC-008 | 生产环境必须配置 HTTP 安全响应头：Content-Security-Policy、Strict-Transport-Security、X-Content-Type-Options、X-Frame-Options、Referrer-Policy、Permissions-Policy | P0 |
| NFR-SEC-009 | 后端 CORS 策略必须限制 allowed origins 为前端域名白名单，禁止通配符 | P0 |
| NFR-SEC-010 | 登录、注册、忘记密码接口不得通过响应差异泄露用户是否存在（防账号枚举） | P0 |
| NFR-SEC-011 | SQL 查询必须使用参数化查询或 ORM，禁止字符串拼接 SQL | P0 |
| NFR-SEC-012 | Cookie 必须设置 Secure、HttpOnly、SameSite=Lax 属性；生产环境禁止 SameSite=None 除非明确需要跨站场景 | P0 |
| NFR-SEC-013 | 登录态必须支持空闲超时（建议 30 分钟无操作）和绝对超时（建议 24 小时），过期后强制重新认证 | P0 |
| NFR-SEC-014 | 管理员账户必须支持 MFA（TOTP 或邮箱验证码二次确认），MVP 至少实现登录时邮箱验证码 | P0 |
| NFR-SEC-015 | GitHub 采集和外部 URL 处理必须防 SSRF：校验目标地址非内网、限制跳转次数、禁止 file:// 和非 HTTP(S) 协议 | P0 |
| NFR-SEC-016 | 工具容器必须以非 root 用户运行，启用 `--no-new-privileges`，建议配置 seccomp 默认 profile | P0 |
| NFR-SEC-017 | 生产环境错误响应禁止返回堆栈跟踪、数据库错误详情和内部路径；服务器 HTTP 响应头禁止暴露框架名称和版本 | P0 |
| NFR-SEC-018 | MySQL、MongoDB、Redis 连接必须启用认证；Redis 必须设置 AUTH 密码并禁用 KEYS 等危险命令 | P0 |
| NFR-SEC-019 | 日志内容必须防注入：用户输入写入日志前必须转义换行符和控制字符 | P0 |
| NFR-SEC-020 | 所有依赖必须使用 lockfile 锁定版本（pip freeze / package-lock.json），CI 中启用依赖漏洞扫描（Dependabot 或 Trivy） | P0 |
| NFR-SEC-021 | 数据库备份文件必须加密存储，传输使用 TLS；建议生产数据库启用 TDE 或磁盘加密 | P1 |
| NFR-SEC-022 | 用户可以请求删除账户和导出个人数据（GDPR/个保法合规预留），账户删除后个人信息不可恢复 | P1 |
| NFR-SEC-023 | 全站必须具备 DDoS 基础防护：建议接入 CDN/WAF（如腾讯云 WAF），单 IP 全局请求速率上限 | P0 |
| NFR-SEC-024 | 密码必须强制复杂度策略：最少 8 位，包含大小写字母和数字，禁止常见弱密码 | P0 |
| NFR-SEC-025 | 文件上传必须校验实际文件内容（magic bytes），不仅依赖扩展名；上传文件必须通过独立域名或 CDN 路径提供，不得与主站同源 | P0 |
| NFR-SEC-026 | 论坛和博客中用户提交的外部链接必须标记 `rel="noopener noreferrer nofollow"`，防止钓鱼和 referrer 泄露 | P0 |
| NFR-SEC-027 | 必须建立安全事件响应流程：包括事件分级、通知机制、处置流程、事后复盘模板 | P0 |

### 5.2 性能

| 编号 | 需求 | 指标 |
|---|---|---|
| NFR-PERF-001 | 普通 API P95 响应时间 | <= 500ms |
| NFR-PERF-002 | 文章详情首屏可用时间 | MVP 阶段应适配 CDN/SSR/预渲染优化 |
| NFR-PERF-003 | 列表接口 | 必须分页，默认 page size <= 20 |
| NFR-PERF-004 | 工具任务排队 P95 | <= 60 秒，超出需告警 |

### 5.3 可用性与可恢复

| 编号 | 需求 | 优先级 |
|---|---|---|
| NFR-REL-001 | `/health` 健康检查接口 | P0 |
| NFR-REL-002 | MySQL 每日备份，MongoDB 定期快照 | P0 |
| NFR-REL-003 | 上线前完成备份恢复演练 | P0 |
| NFR-REL-004 | 每次发布保留上一稳定版本回滚路径 | P0 |

### 5.4 可观测性

| 编号 | 需求 | 优先级 |
|---|---|---|
| NFR-OBS-001 | JSON 结构化日志包含 request_id、user_id、route、status、latency | P0 |
| NFR-OBS-002 | 工具任务通过 job_id 串联 API、Worker、日志和前端状态 | P0 |
| NFR-OBS-003 | 监控 API 错误率、P95、队列长度、工具成功率、邮件成功率 | P0 |
| NFR-OBS-004 | 关键异常需要告警 | P0 |

### 5.5 SEO

| 编号 | 需求 | 优先级 |
|---|---|---|
| NFR-SEO-001 | 博客详情、项目详情、工具详情输出 title、description、canonical | P0 |
| NFR-SEO-002 | 自动生成 sitemap、robots.txt、RSS | P0 |
| NFR-SEO-003 | 文章内容应支持 SSR 或预渲染 | P0 |
| NFR-SEO-004 | 分类页、标签页应具备可索引 URL | P1 |

### 5.6 UI 与可访问性

| 编号 | 需求 | 优先级 |
|---|---|---|
| NFR-UI-001 | 论坛 UI 必须使用统一设计 token，包括颜色、字体、间距、圆角、阴影和状态色 | P0 |
| NFR-UI-002 | MVP 至少实现 `fintech-trust-light` 和 `terminal-agent-dark` 两个主题，推荐预置 `minimal-focus` 和 `research-docs-light` | P0 |
| NFR-UI-003 | 主题切换后无需刷新即可生效，刷新后保持用户选择 | P0 |
| NFR-UI-004 | SSR 首屏应读取 cookie 中的主题偏好，避免明显主题闪烁 | P0 |
| NFR-UI-005 | 所有主题文本对比度、焦点态、危险操作和状态标签必须满足基础可访问性要求 | P0 |
| NFR-UI-006 | 主题设计可参考 DESIGN.md 风格抽象，但不得复制第三方品牌 logo、专属字体和商标化视觉资产 | P0 |

---

## 6. 数据需求概览

核心数据实体：

1. User。
2. Role。
3. BlogPost。
4. Category。
5. Tag。
6. ForumThread。
7. ForumReply。
8. Tool。
9. ToolJob。
10. GitHubProjectSnapshot。
11. AuditLog。
12. Event。
13. UserPreference。

数据治理要求：

1. 用户内容默认软删除。
2. 敏感字段不进入日志。
3. 工具任务原始输入输出设置保留周期。
4. 内容正文和工具配置建议保留版本。
5. 分析事件与核心业务表解耦。

---

## 7. 接口需求概览

API 基线使用 `/api/v1`。

核心接口组：

1. `/api/v1/auth/*`。
2. `/api/v1/users/me`。
3. `/api/v1/blog/*`。
4. `/api/v1/forum/*`。
5. `/api/v1/tools/*`。
6. `/api/v1/open-source/projects/*`。
7. `/api/v1/admin/*`。
8. `/api/v1/events`。
9. `/api/v1/newsletter/*`。

接口要求：

1. 所有列表接口支持分页。
2. 统一错误格式包含错误码、错误信息、request_id。
3. 写接口需要权限校验、输入校验、限流。
4. 幂等场景需要防重复提交。
5. OpenAPI 文档必须与实现保持一致。

---

## 8. 验收映射

| 需求组 | 验收文档章节 |
|---|---|
| Auth | `05-验收测试与上线验收文档.md` 4.1 |
| Blog | `05-验收测试与上线验收文档.md` 4.2 |
| Forum | `05-验收测试与上线验收文档.md` 4.3 |
| Tools | `05-验收测试与上线验收文档.md` 4.4 |
| Discovery | `05-验收测试与上线验收文档.md` 4.5 |
| Admin | `05-验收测试与上线验收文档.md` 4.6 |
| Security | `05-验收测试与上线验收文档.md` 5 |
| UI Theme | `05-验收测试与上线验收文档.md` 6.4 |
| Launch | `05-验收测试与上线验收文档.md` 7 |

---

## 9. 需求变更规则

1. P0 功能变更必须同步更新 PRD、SRS、设计和验收文档。
2. 涉及数据库、权限、安全、工具执行的变更必须重新评审。
3. 未进入 SRS 的需求不能直接进入开发。
4. 验收标准不明确的需求不能进入迭代。
