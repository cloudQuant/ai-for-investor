# ai-for-investor 新许可适用范围草案

**状态：草案，未生效，不授予或撤销任何许可。当前仓库根 LICENSE 仍为 MIT。**

参考快照：`/Users/yunjinqi/Documents/new_projects/ai-for-investor`，分支 `feature/a5-opendata-provider`，HEAD `50b6a54baa6a7d9424bc3b3664c399c297908852`。证据和阻塞见同目录 `LICENSE-REVIEW.md`。

## 拟采用原则（共同条款仍须审阅）

1. 对有权采用新许可且在最终清单中明确列出的未来版本内容，源码长期公开；未经单独许可不得进行最终条款所定义的商业使用。
2. 个人仅使用自己的资金做回测、模拟交易和实盘交易，明确免费允许；个人自有资金的交易收益不因收益本身被定义为需付费的商业使用。
3. 不设自动转开源日期。新许可属于源码可见许可，不称为开源许可或标准 BSL，也不借重命名来改写或规避 BSL 标准文本的限制。
4. 用户已确认：个人本人自有资金免费；为他人管理资金、收费服务或商业产品集成、企业内部使用需另行书面授权。个人免费用途中的常规集成不属于商业产品集成。其他例外仍待审，正式文本、权属白名单和生效版本尚未批准；本政策确认不使草案生效。
5. 不加入未经用户决定的仲裁、管辖地、专利、赔偿或宽泛版权转让承诺。

## 新版本与历史授权边界

| 项目 | 待确认值 |
| --- | --- |
| 许可正式名称与版本 | 待审阅；不得使用标准许可名称伪装自定义条款 |
| 有权授权的许可人 | 待逐文件权属核验，不仅凭根版权行确定 |
| 生效版本/标签 | 未确定 |
| 生效提交 | 未确定；上面的参考 HEAD 不是生效承诺 |
| 许可适用文件及哈希 | 未确定；当前核准白名单为空 |
| 历史 MIT 边界记录 | 待补实际发布版本/标签/提交及对应许可文本 |
| 第三方/其他许可例外清单 | 见下表，仍须补来源和对应文本 |

新许可只能向前作用于有权授权、在明确新版本和文件清单中提供的内容，不能追溯撤销已按 MIT、GPL、BSL 或其他许可提供的旧版本授权。不能仅以文件的修改日期、目录归属或维护者的单个版权行，将历史第三方内容视为已清权。未来获准的新版本可以另行提供适当范围的条款，已经获得旧版本的人仍可依旧版有效许可使用该旧版。

## 适用清单模板

**当前批准项：无。以下只是待核验模板，不能据此替换根许可。**

| 文件精确路径 | 新版本文件哈希 | 版权人 | 原创/来源证据 | 权利人授权依据 | 决定 |
| --- | --- | --- | --- | --- | --- |
| [逐文件填写，不使用全仓通配符] | [待填] | [待填] | [待填] | [待填] | 待审 |

只有完成以上字段且明确审定为可重新许可的文件，才能加入正式白名单。新创作文件也须排除第三方复制内容，不能凭“新文件”自动视为全部原创。若确认内容仅能保持原许可或与新限制不兼容，则继续保留原文件及原许可，必要时从未来单独许可的分发范围中剥离；本轮不修改业务代码以实现剥离。

## 必须保留的例外与暂缓范围

| 范围 | 本轮决定 | 生效前要求 |
| --- | --- | --- |
| 当前根 `LICENSE`、历史 MIT 版本和旧授权 | 保持 | 保存原文；明确新旧版本边界 |
| 历史他人贡献及无明确权属证据的现有文件 | 暂缓纳入 | 查明作者与权利归属、取得必要授权；MIT 入站许可不等于版权转让 |
| Fincept 台账所列 Data Connector Registry、Data Topic Hub、Portfolio Ledger、News/Options/Quant Tools、相关前端和文档 | 暂缓纳入 | 完成独立实现审查、签署、来源及提交映射，不因自查声明视为已清权 |
| 独立 bt_api_py broker contract | 不由本仓清单覆盖 | 由独立仓库单独审阅，不据台账引用扩展范围 |
| Backtrader 引擎、GPL 内容及可能受其义务影响的组合分发 | 保留上游许可；暂不作新限制兼容认定 | 检查直接导入/继承、安装包、镜像和部署分发；审阅对应源代码及 GPL 义务 |
| `docs/reference/akshare/**` | 排除新许可候选范围 | 保留上游来源；核查文档许可与数据供应商授权 |
| 其他第三方文档、工具/技能素材、依赖、SDK、图像、数据 | 不由新许可覆盖 | 逐项来源、许可及声明核对；不删除原版权/署名 |

## 将来配套说明的建议文本（未生效）

README 中文许可段建议：

> 自 [确认的新版本/提交] 起，本项目仅对 [正式适用清单] 中列明且有权授权的内容采用 [最终许可名称和版本]。源码长期公开，该许可为源码可见许可，未经单独许可不得进行条款所定义的商业使用，且没有自动转为开源许可的期限。个人使用自己的资金进行回测、模拟交易和实盘交易免费允许，交易收益本身不使其成为需付费的商业用途。旧版本仍受其发布时的许可约束；第三方内容及 Backtrader 保留各自许可，详见许可清单和第三方声明。

README 英文许可段建议：

> Starting with [confirmed release/commit], only the content identified in [approved file scope] and authorized for relicensing is provided under [final license name and version]. Its source remains publicly available. This is a source-available license; commercial use as defined by its terms requires separate permission, and there is no automatic conversion to an open-source license. An individual may backtest, paper trade, and trade live with their own funds free of charge. Returns on those funds do not, by themselves, make that use a paid commercial use. Previously released versions retain the licenses under which they were provided. Third-party content and Backtrader retain their respective licenses, as identified in the scope and notices.

以上示例须在正式条款及权属范围确认后再同步至根 README、前后端 README、贡献说明和包元数据；当前仓库继续保留 MIT 声明。律师应审阅最终条款及 GPL/第三方兼容性，本草案不保证法律效力。

## 前一阶段交付范围

本轮实际只新增 `LICENSE-SOURCE-AVAILABLE-DRAFT.md`、`LICENSE-SCOPE-DRAFT.md`、`LICENSE-REVIEW.md` 三份未生效审阅文件。根许可、README、贡献说明、元数据、第三方声明及用户原有改动保留；未提交、未推送。

## 本次免责声明增量

新增 [免责声明与使用风险草案](DISCLAIMER.md)，并在 README 提供入口。该草案尚未批准生效，风险建议不是许可条件；现有许可、第三方免责及用户既有改动保持。基础商业政策的确认不撤销任何旧版权利；本次未提交或推送。
