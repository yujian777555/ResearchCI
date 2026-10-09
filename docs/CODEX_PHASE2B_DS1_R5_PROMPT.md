# Codex Executor — ResearchCI Phase 2B-DS-1-R5

你是 ResearchCI 的 Executor，ChatGPT 是 Planner。继续已有 GitHub 项目，不要初始化，也不要根据聊天报告猜测真实代码状态。

仓库：https://github.com/yujian777555/ResearchCI
分支：main
Issue：https://github.com/yujian777555/ResearchCI/issues/17
唯一权威规范：docs/PHASE2B_DS1_R5_PLAN.md
Planner 规范 commit：51e827f05ea82a201347dfff0f447b67fc549f0c
已接受 R4 commit：01fe25f10bb6f5001054652a975161abf9eebfc5

## 任务定义

R5 是 **严格离线** 的 DeepSeek 真实 HTTP transport cutover 准备，不是对真实 API 调用的授权。

执行顺序：

1. git fetch && git pull --ff-only，检查 HEAD==origin/main 且 clean。完整阅读 R5 Planner 规范、原 DS-1 与 R4 文件、SDK factory、transport audit、CLI、qualification gate、测试和冻结报告。
2. 从 R4 已验证的同一真实 OpenAI-compatible SDK factory 延伸生产 httpx2.HTTPTransport 实现，保持 models.list() / responses.create() 结构一致、明确 max_retries=0、transport retries=0、trust_env=False、TLS 校验、有限超时与 audit。默认禁用真实 transport，无独立授权不能创建真实请求。
3. 建立一条受控 future replacement preflight 准入链：指定 stage PRECHECK_ONLY、授权关联 exact harness commit、一次性 run ID、提交前冻结、检查 HEAD==origin/main/clean、持久化 single-use reservation、请求前审计日志，发生 crash/timeout/unknown 不可自动重跑。当前 R5 不创建有效线上授权。
4. R5 测试只使用 synthetic key 和 MockTransport，真实 SDK models.list() 覆盖 target present/absent、401、402、429、500/503、timeout、connection、malformed、audit crash 和 process restart，确认 HTTP attempts 与 SDK invocations 可区分。模拟合格也绝不能触发 POST /responses 或 live canary。
5. 在离线测试中验证不批准、wrong stage、wrong SHA、dirty worktree、untrusted run ID、duplicate token、already consumed、uncertain transport count、crash restart 等均 fail closed。用与未来 production 相同的状态转换函数，不能另造一条假通过。
6. 不改冻结 DeepSeek DS-0-R1 hash sha256:07cc0a68ec471f796dbc312c39f8386b6ff956d64524043adc11632c4bb448fe；不改冻结 STATS-0-R1 hash sha256:e6e262d95c55611f48541637a7ffbb8d75421632324030b52b0dd03477b5a083。
7. 允许范围仅 agentbench/deepseek_live_canary/**、新 R5 离线 tests、新 phase2b_ds1_r5_*.json 报告。禁改 core/C001-C006/A0-A4、Phase 2A、provider adapter/protocol、analysis、system prompt、tool schema、以及历史 DS-1 failure/R1/R2/R3/R4 reports。
8. 完整 pytest 0 failed；新增 phase2b_ds1_r5_diagnostic.json、phase2b_ds1_r5_offline_e2e.json、phase2b_ds1_r5_regression.json、phase2b_ds1_r5_scope_audit.json、phase2b_ds1_r5_harness_freeze.json，记录 source/client/ledger/schema/test hashes。
9. commit message: Phase 2B-DS-1-R5: freeze offline live-transport cutover；push main，验证 HEAD==origin/main、clean、完整 SHA，然后 STOP。

## 绝对禁止

R5 不得读取 DEEPSEEK_API_KEY 或 OPENAI_API_KEY（包括仅查看环境变量存在性）。不得访问真实 provider API。真实 DeepSeek/OpenAI API calls=0，实际 provider network=0，真实凭据读取=0，live canary=0，benchmark=0。

第一次 DS-1 请求的 FAIL_PREFLIGHT_ARTIFACT 原始证据及 UNKNOWN HTTP/credential/model status 必须保留。不得为了获取事实再次运行 GET /models。

下次真实 GET /models 是独立的、由用户和 Planner 明确授权的 replacement request；R5 完成不构成授权。Canary 更需要独立批准。

## 回报模板

Phase 2B-DS-1-R5 COMPLETE / OFFLINE — STOP

Implementation commit:
Final remote HEAD:
Working tree:
Full regression:
R5 new tests:
Production transport default disabled:
SDK max_retries:
Transport retries:
One-use ledger test:
Wrong authorization/restart/unknown fail-close tests:
Mock GET /models attempts:
Preflight PASS cannot start canary:
Frozen DeepSeek protocol hash:
Frozen STATS protocol hash:
R5 harness/source/ledger hashes:
Scope and credential audits:
Actual external API calls: 0
External provider network calls: 0
Real credential reads: 0
Live canary episodes: 0
Benchmark episodes: 0
Deviations:
STOP

不要自行关闭 Issue #17；等待 Planner 代码验收。
