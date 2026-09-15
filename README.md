# Sales Research Agent

面向售前工程师的证据驱动型公网调研 Agent。项目以可信度为硬门槛、效率为第二目标，通过 LangGraph 编排调研计划、信息采集、证据抽取、事实核验和报告生成，使报告中的外部事实可以追溯到原始来源。

当前处于 **本地 CLI MVP**：可恢复 Graph、证据门禁、网页/PDF 摄取、异常降级和双格式 Intelligence Brief 已通过离线验证；报告正文面向售前会前阅读，来源、原文证据和研究质量进入可追溯附录。海尔智家与比亚迪案例均已运行，多次运行稳定性和 Fact 人工审阅已记录。项目暂不定位为多人生产服务。详见 [MVP 验收清单](docs/mvp-acceptance-checklist.md)、[报告输出契约](docs/intelligence-brief-report-contract.md)、[比亚迪真实运行审阅](docs/poc/2026-09-11-byd-live-run-review.md) 与 [重复运行稳定性记录](docs/poc/2026-09-11-repeated-run-stability.md)。

真实案例使用 `uv run sales-research run --case <case.json> --live` 执行。2026-09-12 完成 P0 正确性收口及评审修复后，本地离线验证结果为 `120 passed, 1 deselected`，并通过 `ruff check .` 与 `mypy src`。随后经授权执行比亚迪真实公网验收：持久化遥测与实体隔离通过，但发现一个 GBK 页面产生 8 条乱码 Evidence，因此本次报告终态为 `PARTIAL`，不能视为内容质量完全通过。

P0 收口补齐了并行研究实体与模型制品隔离、共享来源的多问题覆盖、可跨恢复审计的外部调用遥测，以及 CLI 测试与开发者 `.env` 的隔离。新运行使用 runtime version 2；历史 version 1 报告仍可查看和检查，但不允许由新版继续恢复。

## 当前范围

- 第一主场景：陌生客户首次交流前的公网调研
- 第一核心用户：售前工程师个人使用
- 输出：适合会前完整阅读的 Markdown 与 HTML 调研报告
- 数据：仅使用公网信息，不接入聊天、AIOps 或企业内部材料
- 持久化：第一版采用 SQLite 和本地文件系统

## 已完成文档

- [产品与架构决策](docs/product-and-architecture-decisions.md)
- [现有项目代码审计](docs/current-state-audit.md)
- [能力迁移与目标架构](docs/capability-migration-and-target-architecture.md)
- [领域模型与节点契约](docs/domain-model-and-node-contracts.md)
- [技术设计自审摘要](docs/technical-design-review-summary.md)
- [项目开发复盘与面试讲解](docs/project-development-retrospective-and-interview-guide.txt)
- [阶段 0：POC 风险验证规格](docs/superpowers/specs/2026-09-10-risk-validation-poc-design.md)
- [阶段 0：POC 实施计划](docs/superpowers/plans/2026-09-10-risk-validation-poc-implementation.md)
- [真实运行人工审阅模板](docs/poc/live-run-review-template.md)
- [POC 决策记录模板](docs/poc/decision-record-template.md)

## 交互原型

- [售前可信调研工作台](prototype/presales-research-workbench.html)

## 下一步

已完成[内容可信度修复与真实复验](docs/content-trust-hardening.md)：显式 HTML 解码、损坏正文阻断，以及报告来源与日期约束。`APPROVED` 表示原文与语义支持通过；非一手或日期不明的陈述会保留为待核实明细，不进入当前事实摘要。

可使用 CLI 或本地浏览器入口运行“输入背景 → 生成计划 → 公网搜索与抓取 → 提取事实和证据 → 引用核验 → Markdown/HTML 报告”闭环。浏览器入口：`uv run sales-research web`，默认地址为 `http://127.0.0.1:8765`。

## 本地开发

默认 `uv run pytest` 为离线测试，并排除标记为 `live` 的测试，不访问公网也不要求 API 密钥。离线验收使用 Fake Provider 与本地 HTML，并检查 domain/checkpoint SQLite、原始与清洗制品、双格式报告、统计及密钥泄漏门禁。

真实运行前，将密钥仅保存在本地 `.env` 或环境变量中，随后显式执行：

```powershell
uv run sales-research run --case evals/cases/haier_first_meeting.json --live
```

运行完成后使用 `sales-research inspect --run-id <run_id>` 查看脱敏汇总。汇总包含运行版本、终态、耗时、搜索/网页/PDF/模型调用次数、来源结果和 Claim 数量；随后按审阅模板逐条核对全部外部 Fact。密钥不得提交到版本库、运行制品、日志或审阅文档。

MVP 公开案例包括海尔智家和比亚迪：

```powershell
uv run sales-research run --case evals/cases/haier_first_meeting.json --live
uv run sales-research run --case evals/cases/byd_first_meeting.json --live
```

来源等级通过 `OFFICIAL_HOSTS` 与 `TRUSTED_SECONDARY_HOSTS` 可选配置（Pydantic tuple 使用 JSON 数组格式），用于排序和报告提示，不要求每次启动都维护域名。无论是否配置，报告都会展示来源网页、标题、URL 和证据原文；未命中的域名保持为 `UNCLASSIFIED`，由售前工程师在阅读时自行判断是否为官方网站。
