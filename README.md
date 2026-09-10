# Sales Research Agent

面向售前工程师的证据驱动型公网调研 Agent。项目以可信度为硬门槛、效率为第二目标，通过 LangGraph 编排调研计划、信息采集、证据抽取、事实核验和报告生成，使报告中的外部事实可以追溯到原始来源。

当前处于 **POC 风险验证前的产品与技术设计阶段**，尚未开始功能实现。

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

## 交互原型

- [售前可信调研工作台](prototype/presales-research-workbench.html)

## 下一步

开展风险验证型 POC，跑通“输入背景 → 生成计划 → 公网搜索与抓取 → 提取事实和证据 → 引用核验 → Markdown/HTML 报告”的最小纵向闭环，再依据实测结果冻结 MVP 技术方案并拆分正式交付阶段。

## 本地开发

默认 `uv run pytest` 为离线测试，并排除标记为 `live` 的测试，不访问公网也不要求 API 密钥。需要运行 live 测试时使用 `uv run pytest -m live`，并设置对应环境变量；应用 CLI 的联网模式则使用未来的 `sales-research ... --live`。密钥只应保存在本地 `.env` 文件中，不要提交到版本库。
