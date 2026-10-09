# Codex Executor: ResearchCI Phase 2B-DS-1-R4

你是 ResearchCI 的 Executor，当前 Planner=ChatGPT。请直接读取仓库状态并执行下一轮，勿重复初始化。

**Repo:** https://github.com/yujian777555/ResearchCI
**Issue:** https://github.com/yujian777555/ResearchCI/issues/16
**权威规范:** `docs/PHASE2B_DS1_R4_PLAN.md`
**Planner spec commit:** `2ff464d76f80158f5298b9777cc2ab531b2d5b60`
**已验收 R3:** `cc9ccc6458c5fe70e6650ade9f752d2a765e705a`

**本轮 R4 = 实际 SDK 客户端集成的严格离线冻结。0 真正 API 调用、0 真正外部 HTTP、0 凭据读取、0 live canary、0 benchmark。绝对不允许替代 GET /models 或 POST /responses。**

## A. 状态与约束

1. `git fetch && git pull --ff-only`，检查 `HEAD == origin/main` 且工作区 clean，异常则停止。
2. 先全文阅读 `docs/PHASE2B_DS1_R4_PLAN.md`、DS-1 原规范、R3 commit 的 `agentbench/deepseek_live_canary/**`、DeepSeekRequestBuilder/ResponsesAdapter、EpisodeOrchestrator、RetryPolicy、R3 测试与报告。
3. 当前 DeepSeek 冻结协议 hash 为 `sha256:07cc0a68ec471f796dbc312c39f8386b6ff956d64524043adc11632c4bb448fe`；STATS hash 为 `sha256:e6e262d95c55611f48541637a7ffbb8d75421632324030b52b0dd03477b5a083`。不得修改。
4. 历史第一次 DS-1 `FAIL_PREFLIGHT_ARTIFACT`（结果 commit `d92b541263edea9b749ff70f475fc4aad5b2fce0`）保留，实际 HTTP 次数与 provider outcome 仍 UNKNOWN；不得改写。

## B. 必须实现

1. 统一可注入的 **真实 OpenAI-compatible SDK** 客户端工厂（对应 `models.list()` 与 `responses.create()`），用标准冻结 URL/模型；显式 `max_retries=0`，HTTP 传输无隐式重试，禁用意外环境代理（若依赖支持），设置有界 timeout，审计实际传输层 attempts。R4 不得从环境读取用户 Key，只使用 synthetic key 测试。
2. 同一个构造工厂在离线测试中注入 **MockTransport**，运行真正 SDK 的 GET /models，以及真正 SDK → DeepSeekResponsesAdapter(client=...) → EpisodeOrchestrator → BudgetEnforcer → synthetic mediator → replay → SDK POST /responses。不能只用 `transport=lambda:` 的假响应来假装测试 SDK。
3. MockTransport 必须捕获真实发出的两次 POST JSON 并检查：冻结请求字段、model `deepseek-v4-pro`、`reasoning.effort=max`、`top_p=0.95`、exact tool schema、首次 task、第一次 provider 输出的 reasoning/function_call 投影、exact call_id/function_call_output、第二轮 full-history、禁止 previous_response_id/store/conversation/metadata/parallel_tool_calls/temperature/seed。
4. 用与 DeepSeek Responses 形状一致的模拟 JSON 触发 SDK 真实 Pydantic/解析路径，保证 2 次成功响应，唯一一次 `read_file({"path":"CANARY.txt"})`，正确 marker，`completed`，fake=0、logical live=2、**actual external HTTP=0**。区分 SDK logical calls、MockTransport attempts 与真实网络。
5. 加 401/402/429/5xx/timeout/connection/malformed/no-tool/extra-tool/重复工具等离线行为测试；SDK 不得内部 retry，冻结 orchestrator 的外层重试及 1s/2s backoff 应通过 fake clock/sleeper 验证；失败不触发自动二次 episode。
6. 与 R3 QualificationGate 和 append+fsync、同一 run 证据回读集成；summary 异常不抹去 primary audit，也不能凭内存构造的 PASS dict 进入 canary。
7. CLI 的 `preflight` 与 `canary` **仍然必须禁止真实运行**，保持 fail-closed；可增强 `offline-selftest` 但不可开放一个联网快捷入口。不要请求真实 API Key。

## C. 允许与禁止改动

只允许：`agentbench/deepseek_live_canary/**`、R4 离线测试、新增 `agentbench/reports/phase2b_ds1_r4_*.json`。

严禁改：`src/researchci/**`、`src/researchci_agent/**`、C001–C006/A0–A4、Phase 1/2A 数据/工作区/manifest、`agentbench/deepseek_adapter/**`、`agentbench/deepseek_protocol/**`、`agentbench/analysis/**`、系统提示词/工具 schema、历史 DS-1/OpenAI/DeepSeek/R1-R3 报告。

如冻结 DeepSeek adapter 当前接口不能支持实际 SDK 返回形状，不得偷偷改 provider contract；保留失败证据，提交 blocker 并 STOP，让 Planner 决策。

## D. 交付与 STOP

新增五份报告：
`phase2b_ds1_r4_diagnostic.json`
`phase2b_ds1_r4_offline_e2e.json`
`phase2b_ds1_r4_regression.json`
`phase2b_ds1_r4_scope_audit.json`
`phase2b_ds1_r4_harness_freeze.json`

详细记录 SDK 依赖/版本、factory/hash、GET/POST MockTransport attempts、完整测试矩阵、目标模型/提示词/工具的冻结 hash、审计与历史 lineage、零真实网络/API/credential read。

运行全量 `pytest`，0 failed；commit message：

`Phase 2B-DS-1-R4: freeze SDK-backed activation harness offline`

push main，核实 `HEAD == origin/main`、工作树 clean；输出 commit SHA、全量测试数、新测试、mock wire attempts、fake vs real-SDK mocked E2E、完整 source/protocol hashes、scope/security audit 和 0 actual API/network/key/live/benchmark 次数。

**最终 STOP。不要启动 replacement preflight / live canary / pilot / formal。不要自己关闭 Issue #16。** Planner 会从 GitHub 实际代码验收后单独决定是否授权下次真实请求。
