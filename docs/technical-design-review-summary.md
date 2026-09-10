# 技术设计评审摘要与风险清单

> 日期：2026-09-10  
> 详细依据：`domain-model-and-node-contracts.md`  
> 当前状态：详细设计初稿已完成并自审，等待用户评审；尚未进入实施计划或编码。

## 1. 一句话方案

建立独立 Python/FastAPI 服务，以显式 LangGraph 编排售前公网调研，用规范化 `Source → SourceRevision → DocumentBlock → Evidence → Claim → ReportVersion` 数据链保证所有外部事实可追溯，并用持久化 checkpoint、SQLite 领域库和本地 artifact store 支持失败收敛、断点恢复和报告审阅。

## 2. 已确认的核心决策

1. 新项目独立建设，不在项目 B 的聊天/AIOps 单体上继续堆功能。
2. LangGraph 负责顶层生命周期、条件路由、并行、恢复和人工确认；LangChain 负责模型、structured output 和局部工具抽象。
3. 不整体翻译项目 A；迁移其 Evidence-first、quote 定位、数字保护、引用门禁、失败收敛和测试语义。
4. Graph State 只保存实体 ID 和控制状态，大正文不进入 checkpoint。
5. SQLite 保存结构化领域实体，artifact store 保存网页/PDF原件和报告，checkpointer 保存执行位置。
6. Fact 必须绑定 APPROVED Evidence；Inference/Recommendation 必须追溯到上游 Claim。
7. 报告从 approved Claim 编译，不允许 Reporter 直接根据网页正文补写事实。
8. HTML 和 Markdown 从同一个不可变 ReportModel 生成并做一致性校验。
9. `execution_status`、`report_outcome`、人工审阅进度是三条独立状态轴。
10. PARTIAL 可以不完整，但保留事实的可信门槛不能降低。
11. 高影响冲突生成 NEEDS_REVIEW 报告，不无限阻塞首次 Graph；后续由独立审阅/补研 Graph 处理。
12. 补研沿用 run_id，但使用新的 operation/thread 和不可变 ReportVersion。
13. 30 分钟按用户真实墙钟等待计算；到时停止扩展搜索，优先完成可信结报。
14. 恢复采用 effectively-once 领域写入，不宣称外部调用 exactly-once。
15. 第一版本地单进程运行，默认监听 127.0.0.1，不提前实现多人账号、租户和分布式队列。

## 3. 设计默认值

- Brief 确认是首次流程唯一默认 interrupt；
- 用户取消后不生成报告结果，提前停止结报则继续完成验证；
- 进程崩溃后标记 RECOVERY_REQUIRED，由用户显式 resume，避免自动产生外部费用；
- 单个来源、问题和并行分支局部失败，不击穿无依赖分支；
- 模型 Schema 修正、Query Rewrite、解析降级和 Claim 修订都有硬上限；
- RunSupervisor 承担本地后台 graph task，浏览器/SSE 断开不取消任务；
- SSE 重放来自 AuditEvent，只传状态和安全投影，不输出思维链或未验证报告 token；
- 新报告验证成功前不替换 active version；FAILED revision 不覆盖旧报告；
- 支撑报告的原始产物不参与自动缓存淘汰；
- SQLite 使用 WAL、foreign key、busy timeout 和短事务，不在事务内等待外部调用。

## 4. PoC 决策门

这些问题不能靠继续写文档定论：

1. 搜索 Provider 对中文企业、官方来源的覆盖、成本和限流；
2. MinerU backend 及其对财报、扫描件、表格 PDF 的效果与硬件成本；
3. Trafilatura 的质量阈值以及何时启用 Playwright；
4. 锁定 LangGraph 版本后的 SQLite checkpointer 兼容性和 pending writes 行为；
5. L2 使用同模型隔离上下文还是第二模型；
6. Source 是否跨 run 复用；
7. token、成本、查询、抓取、浏览器和 OCR 的默认额度。

## 5. 风险清单

### P0：会破坏可信承诺

| 风险 | 后果 | 当前控制 | 必须如何验证 |
|---|---|---|---|
| Evidence 能定位但语义不支持 Claim | 形成“真引用、假结论” | 逐 Claim L2、反驳证据、终态门禁 | 人工抽查高影响事实；对比同/异模型验证 |
| PDF/OCR/网页清洗定位漂移 | 引用无法回到原件 | SourceRevision、parser version、页码/bbox/DOM locator | 多类型真实文档 PoC |
| 高影响冲突被自动掩盖 | 报告以确定语气误导客户交流 | DISPUTED/NEEDS_REVIEW 路由 | 冲突夹具和人工裁决用例 |
| Report 生成引入新事实 | 绕过 Evidence 门禁 | ReportModel 只接 approved Claim；摘要引用正文 Claim | 双格式和摘要差异测试 |
| Prompt injection/SSRF | 越权调用、访问内网或污染报告 | 确定性 Graph、untrusted boundary、逐跳网络校验 | 安全测试与恶意 fixture |

### P1：会破坏恢复、成本或可用性

| 风险 | 后果 | 当前控制 | 必须如何验证 |
|---|---|---|---|
| checkpoint 与领域库双写窗口 | 重放、重复 Evidence 或状态不一致 | NodeOperation、稳定幂等键、事务、result_ref | 每个崩溃窗口故障注入 |
| 外部调用成功但本地未记录 | 恢复后重复调用和收费 | request fingerprint、持久 retry count、预算审计 | Provider adapter 故障注入 |
| 并行分支共同越过预算 | 超时或超成本 | 调用前 reservation | 并发预算测试 |
| 单机进程退出 | 任务中断 | durable checkpoint、RECOVERY_REQUIRED、显式 resume | 杀进程恢复测试 |
| 搜索 Provider 覆盖不足 | 关键官方来源漏检 | Provider port、来源类型要求、Gap 披露 | 中文售前问题小型基准 |
| 动态网页/MinerU 成本过高 | 30 分钟内无法结报 | 按需降级、尾部结报预算 | 真实时间与成本基线 |
| SQLite 写竞争 | SSE/Graph/审阅出现 busy | 单进程、WAL、短事务、busy timeout | 并发集成测试 |

### P2：会扩大工作量或削弱项目表达

| 风险 | 后果 | 控制方式 |
|---|---|---|
| 提前建设多人平台 | 核心可信链路延期 | 第一版只保留 repository/worker 替换接口 |
| 同时接入过多 Parser/Provider | 依赖和测试矩阵失控 | 每类先选一个主实现和一个明确降级 |
| 把全部领域对象塞进 Graph State | checkpoint 膨胀、版本难管 | State 只保存 ID |
| 为了展示 Agent 自由度使用单一 tool loop | 跳过门禁、难恢复 | 顶层显式 StateGraph，局部才使用受限 Agent |
| 在没有基线时宣传百分比提升 | 简历可信度受损 | 只报告带样本规模、日期和运行环境的实测结果 |

## 6. 自审修正摘要

自审已经修正：

- 冲突状态既 interrupt 又 terminal 的矛盾；
- 用户取消被当成 Failure；
- ReportVersion 草稿不能缺少双格式 artifact 的建模问题；
- PARTIALLY_SUPPORTED 事实如何处理不明确；
- SSE 结束事件名可能误导 PARTIAL/FAILED 的问题；
- RECOVERY_REQUIRED 未进入 operation 状态；
- HTTP 返回后长任务由谁继续运行未定义；
- 单个 PDF 解析失败看起来会直接触发 NEEDS_REVIEW。

## 7. 当前评审结论

详细设计已经足以进入分阶段实施计划。实现必须拆成独立验收阶段，先做可信领域内核和摄取 PoC，再做 Graph、报告、API/审阅和真实评测。

进入实施计划不代表 PoC 决策门已经关闭；计划必须把这些未知项安排在它们首次影响实现之前，并为失败候选保留回滚路径。
