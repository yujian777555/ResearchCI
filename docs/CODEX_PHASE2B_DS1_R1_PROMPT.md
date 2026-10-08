# Codex Executor Prompt — ResearchCI Phase 2B-DS-1-R1

你是 ResearchCI 的 **Executor**；我（ChatGPT）是 **Planner**。本轮必须严格执行仓库中已经冻结的规划，完成离线修复、测试、提交与推送，并立即 STOP。**不得执行 DeepSeek API 请求。**

## 0. 唯一权威来源与仓库

- 仓库：https://github.com/yujian777555/ResearchCI
- 分支：main
- 当前 Issue：https://github.com/yujian777555/ResearchCI/issues/15
- **Planner 权威规范：docs/PHASE2B_DS1_R1_AMENDMENT.md**
- Planner 规范提交：4052eea9e64e3027510b9170b4552a0c60119692
- 前次 DS-1 pre-network harness：128758327f8f1b85bc1d73c98339702a691634d7
- 前次 DS-1 失败结果：d92b541263edea9b749ff70f475fc4aad5b2fce0
- 已接受 DeepSeek DS-0-R1 协议：sha256:07cc0a68ec471f796dbc312c39f8386b6ff956d64524043adc11632c4bb448fe
- 已接受 STATS-0-R1 协议：sha256:e6e262d95c55611f48541637a7ffbb8d75421632324030b52b0dd03477b5a083

如果提示词和 Planner 规范冲突，以仓库规范为准；不能自己变更科学假设、协议或准入标准。

## 1. 严格执行顺序

1. git fetch && git pull --ff-only，核对 HEAD == origin/main，工作区 clean。若冲突/不 clean，STOP。
2. 完整读取 docs/PHASE2B_DS1_R1_AMENDMENT.md、docs/PHASE2B_DS1_PLAN.md，以及当前 agentbench/deepseek_live_canary/**、agentbench/live_runner/retry.py、相关预先冻结报告与测试。只读查看历史失败报告。
3. **先复现失败根因，后修代码**：明确 KeyError('api_calls') 在哪个调用栈/哪个序列化入口发生；以真实代码为准，不猜测。
4. 仅离线实现修复、审计、测试；生成 R1 新报告；全量 pytest；范围核查、敏感信息核查。
5. commit + push main；验证 HEAD == origin/main、working tree clean。
6. 输出规定格式，**STOP**。不得自动进入下一阶段。

## 2. 历史事实与失效分类

第一次 DS-1 尝试记录一次 client.models.list() SDK 调用，但真正发送的 HTTP 请求次数没有可靠计数，结果未持久化。无法确认认证、HTTP 状态、目标模型是否存在、请求 ID 或 UTC 时间戳。后续在本地报告序列化处出现 KeyError('api_calls')。

因此保留最终分类 **FAIL_PREFLIGHT_ARTIFACT**；绝不改写为 FAIL_AUTH、FAIL_TARGET_MODEL_ABSENT 或 PASS。未发出 /responses 请求，未运行 canary；所有第一次尝试的 GitHub 报告及提交必须保持不变。也不能通过再次请求来“补写”丢失的结果。

## 3. 修复 A：定位和重现序列化错误

- 搜索 KeyError('api_calls')、requests、api_calls、preflight result serialization 等代码/运行脚本位置，追踪实际数据字段与访问路径。
- 若原执行入口是**未跟踪的一次性脚本/终端命令**，如实记录“未跟踪 / 源码是否可恢复”，绝不虚构原始代码、请求响应或时间戳。
- 写一个确定性的 fake preflight fixture，复现旧序列化 schema mismatch，然后用唯一权威、显式验证的结构化结果 schema 修复。
- 缺少字段、错误类型、结果 UNKNOWN 必须严格区分，fail closed；任何本地序列化异常都不能变成 preflight PASS，不能触发自动重试。
- 对字典中已知旧字段别名的迁移如确有必要，必须有明确定义与测试，不能以默认 0/False 冒充观测事实。

## 4. 修复 B：可追溯且抗崩溃的预检审计

引入 **Git 跟踪的唯一 DS-1 执行入口**，提供严格分离的三种模式：
- offline-selftest：仅 synthetic/fake，本轮允许。
- preflight：本轮必须明确拒绝 live 运行；未来只有新的 Planner 授权、显式允许标记以及新的预先冻结 harness commit 才能使用。
- canary：本轮必须明确拒绝 live 运行；未来还必须有同一授权执行中已经可靠落盘的 preflight PASS 证据。

不要使用 ad-hoc PowerShell/python -c/notebook 作为权威执行入口。

为未来调用设计、离线测试以下独立字段：
- sdk_invocations
- http_attempts_observed
- http_attempt_count_verified
- responses_http_attempts_observed
- provider_outcome_observed
- provider_outcome_persisted

必须可注入 HTTP transport / client 以观察**真实传输层 attempt**，不能用一次 SDK 函数调用推断一次 HTTP 请求。未来的模型列表 preflight 客户端必须 max_retries=0。若 transport instrumentation 未得到有效证据，记录 UNKNOWN / unverified 并 STOP。

构建 sanitised、append-only、崩溃后仍可检查的原始事件日志，以及 schema-validated、atomic-write 的派生 JSON summary。原始事件至少包括请求前 UTC、观测到的 HTTP attempt、响应或失败时间、request ID/HTTP status（如有）、目标模型 ID 是否出现、结果是否持久化。不得保存完整 model catalog、headers、Bearer 或 key。

必须做到：故意在 summary serializer 注入异常，**已经观察并持久化的 preflight 结果与审计事件仍在**，但 qualification 不能虚报 PASS。所有这类测试都通过 fake transport，不访问公网。

## 5. 修复 C：Canary 的真实重试退避不能被绕过

已提交的 agentbench/deepseek_live_canary/canary.py 在 orchestrator 调用里使用 sleep=lambda _:None，会跳过真实 backoff。

- 生产/live 代码改用 EpisodeOrchestrator 的默认 sleep / time.sleep。
- 只有显式离线测试可以注入 no-op 或 fake sleeper。
- 未来 OpenAI-compatible SDK client 的隐式 retry 必须禁用，允许的重试由现有 EpisodeOrchestrator + 已冻结 RetryPolicy 执行。
- 不改现有 retry-policy JSON、max_retries、backoff 参数、BudgetEnforcer、timeout 或 token budget。
- 离线注入 retryable 429/5xx，验证冻结退避被调用、attempts 和 accounting 正确、预算不重置、工具不会因 replay 重复执行。
- 不得真的 sleep 长时间或真实网络请求；用 fake clock/sleeper。

## 6. 修复 D：Canary 合格判定的离线测试

保持合格标准不变。修复和测试以下实际代码路径：
- CANARY.txt 精确 marker：RESEARCHCI_DEEPSEEK_CANARY_OK_DS1。
- agent-visible task 必须精确对齐 docs/PHASE2B_DS1_PLAN.md 的标点与反引号要求；如和前次 harness 不一致，修正为新版本并在报告中记录变更，**不篡改旧 harness 历史**。
- 唯一合法动作 read_file，参数精确 {"path":"CANARY.txt"}，只执行一次；其他路径/工具拒绝。
- 使用权威 EpisodeOrchestrator → DeepSeekRequestBuilder/Adapter → BudgetEnforcer → synthetic mediator，不能旁路。
- 读取真实形状的 assistant message.content 数组内 output_text.text，不得使用 str(list) 来提取 final text；对最终 marker 进行 exact substring 匹配。
- 精确保留 provider call_id，验证 response→input projection、初始 task、function_call_output，以及 stateless full-history replay。
- 零调用、额外调用、错误路径、final marker 缺失、replay 不合法、provider incomplete 均不得通过资格判定。
- 加一个 fail-closed 的合格判定/报告层，显式从事件验证每个 gate；不得只看 termination_reason == completed。
- 不加载 agentbench/scenarios、Phase 2A evaluator metadata 或 benchmark manifests。

## 7. 不可触碰范围

严格禁止修改：
- src/researchci/**、src/researchci_agent/**，C001-C006 与 A0-A4 科研语义；
- Phase 1/Phase 2A scenarios、workspaces、manifests；
- agentbench/deepseek_adapter/**、agentbench/deepseek_protocol/**；既定 DeepSeek DS-0-R1 协议；
- agentbench/analysis/**；STATS-0-R1 统计协议；
- system_prompt、tool_schema；
- OpenAI 相关冻结与 canary 证据；
- **前次 DS-1 失败结果 JSON** 及历史提交。

仅允许窄改 agentbench/deepseek_live_canary/**，增加新 R1 tests 和以下新报告。若确实必须越界，STOP 请求 Planner 决策。

## 8. 必须交付的新增报告

- agentbench/reports/phase2b_ds1_r1_diagnostic.json
- agentbench/reports/phase2b_ds1_r1_offline_e2e.json
- agentbench/reports/phase2b_ds1_r1_regression.json
- agentbench/reports/phase2b_ds1_r1_scope_audit.json
- agentbench/reports/phase2b_ds1_r1_harness_freeze.json

每份报告要保留 parent commit/hash、实际变更路径、失败归因、证据未知项，不允许修饰或倒填历史。新 freeze 至少哈希新 harness source、task、marker、serializer schema、audit contract、retry reference 和有关测试。

## 9. 测试与禁止事项

本轮必须运行完整 pytest，保证旧 OpenAI、DeepSeek DS-0-R1、STATS-0-R1、DS-1 预检测试不回退，并新增覆盖：
- 原 api_calls KeyError 的 offline reproducer 与 fixed serializer；
- missing/mistyped fields fail-closed；
- derived JSON 序列化失败不丢失 primary event evidence；
- preflight 失败、模型缺失、模型存在、响应缺失、UNKNOWN 等不同分支；
- SDK invocation 与 HTTP attempt 的计数区分，implicit SDK retry=0；
- preflight 未持久化 PASS 则 canary 入口拒绝运行；
- 有限次数执行门，不会因错误自动进行第二次 preflight/canary；
- 生产 retry backoff 不是 no-op，工具调用不重复；
- marker、call_id、合法 tool、assistant output_text；
- redaction 与禁止 benchmark 加载；
- 历史 DS-1 五份结果未被修改。

明确要求 **0 API calls、0 runtime network calls、0 credential value reads、0 live episodes、0 benchmark episodes**。fake provider calls 不能报成 live API calls。

不允许调用 GET /models、POST /responses，也不允许通过 shell/curl/httpx/SDK 偷偷联网。

## 10. Commit 与停止条件

先运行全量 pytest，保存结果和 scope/credential audit，再提交：

Phase 2B-DS-1-R1: harden offline preflight audit and canary harness

Push main；确认完整 SHA、远端 HEAD == 本地 HEAD、工作区 clean；然后 **STOP**。

任何修复完成都不授权重测 DeepSeek。仅 Planner 未来可单独批准一次明确标记的 replacement preflight。

## 11. 必须返回的完成报告

**Phase 2B-DS-1-R1 COMPLETE / BLOCKED**

- implementation commit / final remote HEAD / branch / clean 状态
- full tests passed/failed；新增 R1 tests；旧测试回归
- 原 KeyError 的准确 root cause、是否找到了原执行脚本、离线复现证据
- serializer schema 修复内容、UNKNOWN 与 False 区分、序列化失败保留原始事件的测试
- checked-in entrypoint 路径；offline/preflight/canary 模式及 fail-closed 证据
- SDK 调用计数 vs HTTP attempts 的观测方式、仪表化和 max_retries=0 测试
- retry sleep/backoff 修复及 fake error 回归
- canonical assistant output_text / exact canary marker / single read_file / call_id / replay 测试
- updated R1 harness hash 与旧 harness/结果 SHA
- DeepSeek DS-0-R1 protocol hash unchanged、STATS-0-R1 hash unchanged
- scope audit、credential leakage audit、benchmark isolation audit
- DeepSeek API calls=0、OpenAI API calls=0、runtime network calls=0、live episodes=0、benchmark episodes=0
- deviations / unresolved issues
- **STOP**

不要启动下一阶段，不要替 Planner 关闭 Issue #15。
