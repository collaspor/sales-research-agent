# MVP 验收清单

## 当前阶段

项目当前状态为：**本地 CLI MVP 已完成，Web 入口作为轻量增强已提供**。

POC 已验证核心 Agent 链路、证据可信度门禁、网页/PDF 摄取、异常降级和双格式报告；本地 MVP 已补齐连续运行、人工审阅和浏览器入口。

## 验收门槛

| 验收项 | 当前状态 | 说明 |
|---|---|---|
| 海尔智家真实案例 | 部分通过 | 多次运行均生成报告；部分来源 HTTP 403，报告明确披露失败 |
| 比亚迪真实案例 | 通过 | 6 个来源、5 条批准事实、0 个失败来源 |
| Fact 绑定 Evidence | 通过 | 无证据内容不能进入批准事实 |
| 来源网页可回查 | 通过 | HTML / Markdown 展示标题、URL 和来源等级 |
| PDF 解析 | 通过 | MinerU API 已完成真实调用验证 |
| 失败降级 | 通过 | 单来源失败不会阻断其他来源 |
| 离线回归测试 | 通过 | 2026-09-12：`120 passed, 1 deselected`，Ruff 与 Mypy 通过 |
| 本地交互入口 | 通过 | `uv run sales-research web`，默认监听 `127.0.0.1:8765` |
| 连续运行稳定性 | 通过 | 已完成 5 次真实运行，均无流程级崩溃，见重复运行记录 |
| 售前人工审阅 | 通过 | 海尔和比亚迪批准 Fact 均已逐条核对 Evidence |
| 并行实体隔离 | 通过 | Claim、Verification、Failure 和模型响应制品按问题与来源确定性隔离 |
| 共享来源问题覆盖 | 通过 | 同一来源只摄取一次，并对全部关联研究问题分别执行可信管线 |
| 运行遥测 | 真实通过 | 比亚迪运行记录 44 对 started/finished：搜索 4、HTTP 6、PDF 4、模型 30，0 个中断调用 |
| 多编码 HTML 证据 | 本轮回归通过 | GBK 故障原页可正确解码；损坏正文在模型前阻断，见内容可信度修复记录 |
| 历史运行兼容 | 通过 | version 1 可 inspect 且不改写旧 Schema；新版明确拒绝 resume |

## MVP 完成定义

以下条件已满足，项目状态为“本地 CLI MVP”；本地 Web 入口作为轻量增强，不改变可信度门槛：

1. 两个公开案例均可在 30 分钟预算内生成 HTML 和 Markdown；
2. 连续 5 次运行不出现流程级崩溃；
3. 每条批准 Fact 都能定位到 Evidence 和可点击来源 URL；
4. 403、超时、解析失败等失败均被记录，不被静默吞掉；
5. 售前工程师可以仅通过客户背景和研究目标启动调研；CLI 与本地浏览器入口均可用；
6. 报告中的缺口、失败和来源等级能支持人工复核；
7. README、运行示例和验收记录与实际结果一致。

## 2026-09-12 P0 正确性收口

- 新运行使用 runtime version 2，运行元数据独立于 LangGraph checkpoint；
- Evidence、Claim、Verification、Gap、Failure 和模型响应制品使用 Source—Question 作用域；
- 同一来源关联多个研究问题时，正文只摄取一次，后续研究按关联问题分别执行；
- Tavily、静态网页、MinerU 和 DeepSeek 的实际请求及重试写入两阶段审计事件；
- 每次外部请求记录重试序号和关联实体；遥测无法持久化时受控失败并保存脱敏 Failure；
- Graph 异常会把新运行或恢复运行的元数据终态写为 `FAILED`；
- MinerU 的非法 JSON 或响应结构记录为 `SCHEMA_ERROR`，不再误计为成功；
- `inspect` 保持原字段并增加版本、终态、耗时、调用次数及中断调用数；
- CLI 测试不再读取项目本地 `.env`；
- 真实 Provider 验收已执行，调用遥测、唯一调用 ID、实体 operation key 和敏感信息扫描通过；内容编码质量门禁未通过，详见下节。

## 2026-09-12 P0 真实公网验收

- 案例：比亚迪首次交流；run id：`31f626ce-5fd6-48dc-8bf8-794c8bdd3b68`；
- 耗时 64.92 秒，runtime version 2，执行状态 `FINISHED`，报告结果 `PARTIAL`；
- 6 个来源中 4 个成功、2 个失败，失败分别为 `HTTP_403` 和 `EMPTY_CONTENT`；
- 44 次真实外部请求全部形成 started/finished 闭环：Tavily 4、Fetcher 6、MinerU 4、DeepSeek 30，调用 ID 均唯一；
- Source、Evidence、Claim、Verification、Gap、Failure 的 operation key 均无重复；
- 扫描 43 个运行文件，未发现实际 API 密钥、`Bearer ` 字面量或遥测白名单外字段；
- 生成 Markdown 与 HTML 报告，共 21 条批准事实和 23 条报告 Evidence；
- 一个来源实际为 GBK 编码，当前提取链路产生 8 条乱码 Evidence。这些 Evidence 仍支撑批准 Claim，说明还需要“编码识别 + 乱码拒绝”质量门禁；
- 本次所选来源均为未确认来源等级，且来源没有跨问题复用，因此官方来源覆盖和共享来源真实场景仍未得到本次运行验证；相应离线测试保持通过。

## 暂不纳入 MVP

最新内容可信度修复与复验见 [验收记录](content-trust-hardening.md)。真实复验仍为 `PARTIAL`，原因是来源失败；18 条语义支持陈述均标记待核实，0 条进入当前摘要。历史运行记录保留原结论。

- 多人账号和权限
- 云端部署
- MySQL 替换 SQLite
- 企业内部数据接入
- 自动生成完整售前方案或商务报价
- AIOps 和聊天功能
