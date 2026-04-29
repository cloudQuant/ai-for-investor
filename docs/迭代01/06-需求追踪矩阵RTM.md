# ai-for-investor 需求追踪矩阵 RTM

版本：v0.2  
日期：2026-04-30  
状态：MVP 追踪基线  
关联文档：`01-业务需求文档BRD.md`、`02-产品需求文档PRD.md`、`03-软件需求规格说明书SRS.md`、`05-验收测试与上线验收文档.md`、`07-论坛UI设计规范与主题系统.md`

---

## 1. 文档目的

需求追踪矩阵用于确保每个核心业务目标都能追踪到产品需求、软件需求、设计模块和验收用例，避免出现以下问题：

1. 业务目标没有对应功能。
2. 产品需求没有软件规格。
3. 软件功能没有测试和验收标准。
4. 开发完成后无法判断是否满足原始目标。
5. 需求变更后无法评估影响范围。

---

## 2. 追踪规则

每个核心需求至少应具备以下链路：

```text
BRD 编号 -> PRD 编号 -> SRS/FR/NFR 编号 -> 设计模块 -> 验收用例 AC/SEC/SEO/OBS
```

状态说明：

| 状态 | 说明 |
|---|---|
| Planned | 已规划，未开发 |
| In Progress | 开发中 |
| Ready for Test | 已提测 |
| Accepted | 验收通过 |
| Deferred | 延后 |
| Rejected | 不做或废弃 |

---

## 3. MVP 需求追踪矩阵

| 业务目标 | 产品需求 | 软件需求 | 设计模块 | 验收用例 | 优先级 | 状态 |
|---|---|---|---|---|---|---|
| BRD-001 建立 AI 交易与投资内容入口 | PRD-BLOG-001, PRD-BLOG-002, PRD-BLOG-008 | FR-BLOG-001, FR-BLOG-002, FR-BLOG-008, NFR-SEO-001, NFR-SEO-002 | Blog Module, SEO Design | AC-BLOG-001, AC-BLOG-002, AC-BLOG-008, SEO-001~SEO-005 | P0 | Planned |
| BRD-002 建立社区讨论沉淀 | PRD-FORUM-001~PRD-FORUM-011 | FR-FORUM-001~FR-FORUM-013, NFR-UI-001~NFR-UI-006 | Forum Module, UI Theme Module | AC-FORUM-001~AC-FORUM-015, UI-001~UI-008 | P0 | Planned |
| BRD-003 建立工具体验差异化 | PRD-TOOL-001~PRD-TOOL-007 | FR-TOOL-001~FR-TOOL-008, NFR-SEC-007 | Tool Module, Tool Sandbox | AC-TOOL-001~AC-TOOL-008, SEC-008 | P0 | Planned |
| BRD-004 建立项目发现能力 | PRD-DISC-001~PRD-DISC-006 | FR-DISC-001~FR-DISC-008 | Discovery Module | AC-DISC-001~AC-DISC-006 | P0 | Planned |
| BRD-005 建立可信和合规边界 | PRD-ADMIN-007, PRD-FORUM-005, PRD-TOOL-005 | NFR-SEC-001~NFR-SEC-027 | Admin Module, Security Design (10.1~10.11) | SEC-001~SEC-036 | P0 | Planned |
| BRD-006 建立可持续工程底座 | PRD-DATA-001~PRD-DATA-003, PRD-PAGE-015 | NFR-ARCH-001~NFR-ARCH-007, NFR-OBS-001~NFR-OBS-004, NFR-REL-001~NFR-REL-004, NFR-UI-001~NFR-UI-006 | Overall Architecture, Observability, Deployment, UI Theme Module | OBS-001~OBS-004, UI-001~UI-008, 7.2 技术检查 | P0 | Planned |

---

## 4. 模块级追踪矩阵

### 4.1 用户与认证

| PRD | SRS | 验收用例 | 状态 |
|---|---|---|---|
| PRD-AUTH-001 用户注册 | FR-AUTH-001 | AC-AUTH-001 | Planned |
| PRD-AUTH-002 邮箱验证 | FR-AUTH-002 | AC-AUTH-002, AC-AUTH-003 | Planned |
| PRD-AUTH-003 未验证限制 | FR-AUTH-009, NFR-SEC-001 | AC-AUTH-006, AC-TOOL-009 | Planned |
| PRD-AUTH-004 登录退出 | FR-AUTH-003, FR-AUTH-004 | AC-AUTH-004, AC-AUTH-005, AC-AUTH-008 | Planned |
| PRD-AUTH-005 重置密码 | FR-AUTH-005, FR-AUTH-006 | AC-AUTH-007 | Planned |
| PRD-AUTH-006 管理员用户管理 | FR-ADMIN-001 | AC-ADMIN-003 | Planned |
| (补充) 用户资料更新 | FR-AUTH-007, FR-AUTH-008 | AC-AUTH-009 | Planned |

### 4.2 博客

| PRD | SRS | 验收用例 | 状态 |
|---|---|---|---|
| PRD-BLOG-001 游客浏览文章 | FR-BLOG-001, FR-BLOG-002 | AC-BLOG-001, AC-BLOG-002 | Planned |
| PRD-BLOG-002 分类标签搜索 | FR-BLOG-001 | AC-BLOG-006 | Planned |
| PRD-BLOG-003 后台 CRUD | FR-BLOG-003~FR-BLOG-006 | AC-BLOG-004, AC-BLOG-005 | Planned |
| PRD-BLOG-004 Markdown | FR-BLOG-007 | AC-BLOG-007, SEC-004 | Planned |
| PRD-BLOG-005 风险提示 | FR-BLOG-002 | AC-BLOG-002 | Planned |
| PRD-BLOG-006 关联讨论帖 | FR-BLOG-009 | P1 后续补充 | Deferred |
| PRD-BLOG-007 收藏点赞 | P1 后续补充 FR | P1 后续补充 | Deferred |
| PRD-BLOG-008 SEO 输出 | FR-BLOG-008, NFR-SEO-001~NFR-SEO-003 | AC-BLOG-008, SEO-001~SEO-005 | Planned |

### 4.3 论坛

| PRD | SRS | 验收用例 | 状态 |
|---|---|---|---|
| PRD-FORUM-001 浏览帖子 | FR-FORUM-001, FR-FORUM-002 | AC-FORUM-001 | Planned |
| PRD-FORUM-002 发帖回复 | FR-FORUM-003, FR-FORUM-004 | AC-FORUM-002~AC-FORUM-004 | Planned |
| PRD-FORUM-003 编辑删除 | FR-FORUM-005, FR-FORUM-006 | AC-FORUM-009, AC-FORUM-010, AC-FORUM-011 | Planned |
| PRD-FORUM-004 管理操作 | FR-FORUM-008 | AC-FORUM-005, AC-FORUM-007 | Planned |
| PRD-FORUM-005 举报 | FR-FORUM-007 | AC-FORUM-006 | Planned |
| PRD-FORUM-006 限流 | FR-FORUM-009, NFR-SEC-004 | AC-FORUM-008, SEC-006 | Planned |
| PRD-FORUM-009 论坛 UI 一致性 | FR-FORUM-010, NFR-UI-001 | AC-FORUM-012, UI-006 | Planned |
| PRD-FORUM-010 多主题切换 | FR-FORUM-011, FR-FORUM-012, NFR-UI-002~NFR-UI-004 | AC-FORUM-013, AC-FORUM-014, UI-001~UI-005 | Planned |
| PRD-FORUM-011 主题无侵入 | FR-FORUM-013, NFR-UI-005, NFR-UI-006 | AC-FORUM-015, UI-007, UI-008 | Planned |

### 4.4 工具区

| PRD | SRS | 验收用例 | 状态 |
|---|---|---|---|
| PRD-TOOL-001 查看工具 | FR-TOOL-001, FR-TOOL-002 | AC-TOOL-001 | Planned |
| PRD-TOOL-002 创建任务 | FR-TOOL-003 | AC-TOOL-002, AC-TOOL-003, AC-TOOL-009 | Planned |
| PRD-TOOL-003 查看状态结果 | FR-TOOL-004, FR-TOOL-005 | AC-TOOL-004, AC-TOOL-005 | Planned |
| PRD-TOOL-004 权限隔离 | FR-TOOL-005, NFR-SEC-001 | AC-TOOL-006, SEC-003 | Planned |
| PRD-TOOL-005 风险信息 | FR-TOOL-002 | AC-TOOL-001 | Planned |
| PRD-TOOL-006 工具管理 | FR-TOOL-006, FR-TOOL-007 | AC-TOOL-008, AC-ADMIN-006 | Planned |
| PRD-TOOL-007 高风险工具限制 | FR-TOOL-007, NFR-SEC-007 | AC-TOOL-008, SEC-008 | Planned |

### 4.5 项目发现

| PRD | SRS | 验收用例 | 状态 |
|---|---|---|---|
| PRD-DISC-001 GitHub 采集 | FR-DISC-001, FR-DISC-002 | AC-DISC-001 | Planned |
| PRD-DISC-002 去重评分 | FR-DISC-003, FR-DISC-004 | AC-DISC-002, AC-DISC-003 | Planned |
| PRD-DISC-003 人工审核 | FR-DISC-005 | AC-DISC-004 | Planned |
| PRD-DISC-004 公开项目库 | FR-DISC-007 | AC-DISC-006 | Planned |
| PRD-DISC-005 项目推荐 | FR-DISC-008 | P1 后续补充 | Deferred |
| PRD-DISC-006 项目详情 | FR-DISC-007 | AC-DISC-006 | Planned |

### 4.6 管理后台

| PRD | SRS | 验收用例 | 状态 |
|---|---|---|---|
| PRD-ADMIN-001 用户管理 | FR-ADMIN-001 | AC-ADMIN-003 | Planned |
| PRD-ADMIN-002 文章管理 | FR-ADMIN-002 | AC-BLOG-004, AC-BLOG-005 | Planned |
| PRD-ADMIN-003 论坛管理 | FR-ADMIN-003 | AC-ADMIN-005 | Planned |
| PRD-ADMIN-004 工具管理 | FR-ADMIN-004 | AC-ADMIN-006 | Planned |
| PRD-ADMIN-005 项目发现管理 | FR-ADMIN-005 | AC-DISC-004, AC-DISC-005 | Planned |
| PRD-ADMIN-006 指标总览 | FR-ADMIN-006 | OBS-003 | Planned |
| PRD-ADMIN-007 审计日志 | FR-ADMIN-007 | SEC-010 | Planned |

### 4.7 UI 主题系统

| PRD | SRS | 验收用例 | 状态 |
|---|---|---|---|
| PRD-PAGE-015 主题切换入口 | FR-FORUM-011, FR-FORUM-012 | AC-FORUM-013, AC-FORUM-014, UI-001~UI-004 | Planned |
| 论坛 UI 设计规范 | NFR-UI-001~NFR-UI-006 | AC-FORUM-012, UI-005~UI-008 | Planned |

---

## 5. 变更影响分析模板

当需求发生变更时，按以下模板评估影响：

```text
变更编号：
变更描述：
提出人：
日期：

影响 BRD：
影响 PRD：
影响 SRS：
影响设计模块：
影响验收用例：
影响数据表/接口：
影响安全/合规：
影响排期：

处理结论：接受 / 延后 / 拒绝
负责人：
```

---

## 6. 状态维护规则

1. 需求进入迭代时，状态从 Planned 改为 In Progress。
2. 功能开发完成并部署测试环境后，状态改为 Ready for Test。
3. 验收用例全部通过后，状态改为 Accepted。
4. 延后需求必须说明原因和目标阶段。
5. 需求废弃必须说明替代方案或拒绝原因。
