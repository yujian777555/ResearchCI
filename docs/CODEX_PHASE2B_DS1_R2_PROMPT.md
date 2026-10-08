# Codex Executor — Phase 2B-DS-1-R2 (strictly offline)

你是 ResearchCI 的 Executor。直接接管已运行的 Planner/Executor 流程，不初始化、不重复过去的失败请求。

- Repo: https://github.com/yujian777555/ResearchCI
- Issue: https://github.com/yujian777555/ResearchCI/issues/15
- Planner **权威规范**: `docs/PHASE2B_DS1_R2_AMENDMENT.md`
- Planner R2 spec commit: `7d5fd5cfe287bbf8bdad1f5c776ab40317447f0d`
- 需修 R1 commit: `6ce87b31c6ca31f47fceb71dd969d136b5d007ed`
- DeepSeek DS-0-R1 accepted hash: `sha256:07cc0a68ec471f796dbc312c39f8386b6ff956d64524043adc11632c4bb448fe`
- STATS-0-R1 accepted hash: `sha256:e6e262d95c55611f48541637a7ffbb8d75421632324030b52b0dd03477b5a083`

**本轮只有一个目标：把“不可审计的假通过”变成真实可验证的离线资格验证路径，之后才有资格请求 Planner 单独批准下一次线上 preflight。**

## 执行顺序

1. `git fetch && git pull --ff-only`; assert `HEAD == origin/main`，clean。全文读取 `docs/PHASE2B_DS1_R2_AMENDMENT.md`、DS-1/R1 计划、`agentbench/deepseek_live_canary/**`、`agentbench/live_runner/**`、DeepSeek adapter、相关 tests/reports。
2. 优先写**会在当前代码上失败**的离线行为测试，不允许再用 source-text substring 或无条件返回 0 充当执行验证。
3. 实现唯一受控、可注入、严格 fail-closed 的 offline preflight/canary qualification coordinator + 可观测传输层 + primary audit/summary persistence。
4. 实现完整 fake two-turn canary/正确 assistant output_text 提取/完整 qualification PASS gate；真实运行仍禁止。
5. 用 fake HTTP/SDK/clock 注入执行端到端测试、全量 pytest、scope/secret/lineage audit。
6. 创建 R2 专属新报告，commit/push main，确认同步 clean，STOP。**不要在此回合调用任何真实 DeepSeek API。**

## 阻断项 A：请求计数、审计与资格门

- 目前 `run_preflight()` 的 `http_attempts_observed` 始终为 None，未进行实际 transport instrumentation，也未验证真实 SDK `max_retries=0`。
- 当前第一次 audit append 发生于 `models.list()` 完成之后。请求发生时进程若崩溃，无法保留已有观察到的状态。
- 设计 typed audit events：预检开始、每一次 HTTP transport attempt、收到 response 或 exception、目标模型 presence（True/False/UNKNOWN）、关键状态/时间、outcome 已持久化。
- `PreflightAuditLog.append` 必须只允许白名单字段，且调用实际 redaction，不能保存 Authorization/key/headers/catalog/request body。
- `http_attempt_count_verified` 只能来自**真正安装到请求执行链路的计数器**。测试用 `httpx.MockTransport` 或等效 fake wire path；在客户端层明确 `max_retries=0`，用可重试的假 HTTP 错误证明没有隐藏重试。
- `sdk_invocations` 与 `http_attempts_observed` 不得混用。未观测应为 UNKNOWN，不能造出 0 或 1。
- 在派生 JSON summary 前，已观察 provider outcome 必须先作为 sanitized primary event append+flush+fsync；派生 JSON 采用 atomic-write。
- `provider_outcome_persisted` 只有 primary outcome 成功落盘并完成校验后才可为 True。必须测试模拟 derived serializer 崩溃时 primary evidence 仍保留。
- 原始 KeyError 复现必须显式运行 `legacy_dict["api_calls"]` 之类的真实抛错 fake fixture；不能只 `assert "api_calls" not in dict`。
- 无可信 `PASS + target_present=True + exactly one verified /models transport attempt + persisted primary evidence`，future canary gate 一律拒绝。

## 阻断项 B：CLI 必须真的跑测试

- `python -m agentbench.deepseek_live_canary.cli offline-selftest` 不能只是 `return 0`。
- 它必须通过 fake preflight 与 fake canary 两轮完成真实 coordinator 自检，计数、持久化、状态机门全部验证，不连接网络，不读凭据；注入损坏证据时应返回非零退出码。
- `preflight` 和 `canary` CLI 模式在 R2 **仍然必须 fail closed**，直到 Planner 后续明确放行。不能暗中新增 `--live`、环境变量自动触发或通过任意参数开放真实网络。
- 状态转换必须拒绝第一次 FAIL/UNKNOWN/未持久化的结果，拒绝对同一授权自动二次尝试，禁止自行重启失败的 canary。

## 阻断项 C：真实 canary 结果判定

- `canary.py` 当前用 `str(message.content)`；对于 `[{"type":"output_text","text":"..."}]` 它不是规范 assistant final text。请实现对 supported output_text blocks 的 typed 提取；畸形/无文本严格失败。
- 原 TASK 与 `docs/PHASE2B_DS1_PLAN.md` exact task 的反引号、标点不一致；在新的 R2 harness 中按 Planner 原文修正，登记前后 task hashes。旧 harness / failed result 不改。
- 通过完整 fake Responses provider 两轮交互验证：第一轮仅 1 次 `read_file({"path":"CANARY.txt"})`，mediator 恰好一次，`call_id` 精确保留，真实 output→input projection 正确，第二轮 provider 返回含 exact marker 的 assistant text，`termination_reason=completed`，无 benchmark 加载、无额外工具。
- 资格判定必须明确逐项查 gate，而不只是 `marker_present` 或 `termination_reason`。
- 测试：直接回答 marker 却没调用工具、调用其他工具、重复 read、错误路径、错误 call_id、replay 失效、no text、marker 缺失、provider timeout/incomplete，全部 FAIL。
- 真实 canary 的 backoff 维持 `time.sleep`；在完整 fake orchestrator retry 轨迹中通过注入 sleeper/clock 验证 1s/2s 等冻结退避被调用，预算不重置，tool 不因 replay 执行两次；不能只测试源码中不存在 `sleep=lambda _:None`。

## 范围和结果

可改：`agentbench/deepseek_live_canary/**`，新增/更新 DS-1-R2 离线 tests，以及 **只新增** `agentbench/reports/phase2b_ds1_r2_*.json`。

不可改：科研核心、Phase 2A scenario/workspace/manifest、DeepSeek adapter/protocol、STATS analysis、frozen prompt/tool schema、历史 OpenAI/DeepSeek 证据、原 DS-1 五份失败报告、旧 R1 reports。

必须保留历史 DS-1 `FAIL_PREFLIGHT_ARTIFACT` 分类；HTTP status/目标模型/认证结果仍 UNKNOWN，不得推断。

新增报告：`phase2b_ds1_r2_diagnostic.json`、`phase2b_ds1_r2_offline_e2e.json`、`phase2b_ds1_r2_regression.json`、`phase2b_ds1_r2_scope_audit.json`、`phase2b_ds1_r2_harness_freeze.json`。

Freeze 覆盖：new source、serializer schema、audit contract、canary task/marker、retry policy reference、R2 tests。

**完整 pytest 必须 0 failed；本阶段 DeepSeek/OpenAI API calls=0、network=0、credential reads=0、live canary episodes=0、benchmark episodes=0。**

## 报告格式

完成后输出：
- `Phase 2B-DS-1-R2 COMPLETE / OFFLINE — STOP`
- Implementation SHA, remote HEAD, working tree clean
- Full tests total/failed, R2 behavioral tests count, historical regression
- Explicit KeyError reproducer, serializer/provenance of event evidence, crash injection result
- SDK invocations vs HTTP attempts and transport instrumentation tests, SDK max_retries=0 evidence
- CLI offline-selftest pass **and negative-path failure** evidence; live modes disabled
- Two-turn fake canary exact task/output_text/tool/call_id/replay/FAIL matrix
- Retry/backoff fake E2E, budgets/call counting
- New harness/task/audit/serializer hashes and frozen DeepSeek/STATS hashes
- Scope/audit/secret/benchmark report
- API/network/credential/live/benchmark counts all 0
- Deviations and unresolved limitations
- `STOP`

不要继续执行 preflight、不要请求人工 key、不要调用 `/responses`、不要跑 pilot、不要关闭 Issue #15。等待 Planner 实际 GitHub 代码审查。
