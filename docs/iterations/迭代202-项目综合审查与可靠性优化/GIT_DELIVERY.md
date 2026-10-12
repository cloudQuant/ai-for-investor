# 迭代 200–202 Git 交付范围

用户于 2026-10-12 授权提交并推送本轮代码。目标为当前功能分支 `feature/a5-opendata-provider`，分别推送 GitHub 和 Gitee；不直接更新 dev/master，不在此步骤创建 PR。实际提交 SHA 与逐远端回读结果以交付回复为准。

## 提交范围

- 迭代 200–202 已验收的实现、依赖锁、迁移、配置、测试和文档。
- 六个原有用户文件不混入本次提交：根目录 README 中英文版、DISCLAIMER 以及三份 LICENSE 草稿。
- 代码测试证据沿用[最终验收](FINAL_ACCEPTANCE.md)：本步骤不改变产品源码或测试合同，不把原完整后端批次的 FAIL 改为单轮全绿。

## 原始证据与 Git 存储

原始制品共约 94 MiB。遵循仓库 500 KiB 新文件门槛，文件大小和 SHA-256 保存在 [EVIDENCE_MANIFEST.json](EVIDENCE_MANIFEST.json)：

- `GIT_ORIGINAL`：小型验收日志、结构化收据、源码清单和复核原件直接提交。
- `GIT_GZIP_EXACT`：大文本/JSON/JUnit/JSONL，以及需要保留原始空白的日志和诊断快照使用无损 gzip 提交；解压后字节与原始 SHA 完全一致，原件仍在本地保留。按 manifest 的 `published_path` 读取，例如 `gzip -dc <published_path>`。
- `GIT_STRUCTURED_EXCERPT_AND_LOCAL_RAW`：完整后端复核的公开摘录保留原 FAIL、所有用例结果、计数和原制品哈希，去除可能含凭据形态数据的原始失败堆栈；明确不冒充原件。
- `LOCAL_RAW_ONLY` / `LOCAL_SYMLINK_ONLY`：trace、截图、原始大 JSONL 压缩包、含凭据形态字符串的调试文本，仓库原本忽略的运行日志、冗余历史收据，以及临时构建依赖留在当前工作区，不上传 Git；不跟随 node_modules 符号链接。

原收据中的本地制品路径不表示原件已随 Git 发布；远端审阅时先用 manifest 解析原路径到压缩件/公开摘录，或查看逐例复验映射与小型收据。若需要原始制品，按哈希索引另行脱敏交付。原始失败、跳过、截图均未删除或改写；未放宽大小或秘密检查。THS D04/D05 继续随 OpenData 接入处理。生产发布、真实交易、最低版本浏览器和远端 CI 不因 Git 推送被标为通过。

历史 AkShare 诊断文档的本机链接已转换为仓库相对链接；修改前原件以 `akshare-runner-timeout-diagnosis.original.md.gz` 无损保存并登记哈希。
