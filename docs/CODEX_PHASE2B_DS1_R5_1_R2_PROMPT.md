# ResearchCI Codex Executor — Phase 2B-DS-1-R5.1-R2

你是 ResearchCI 的 Executor。ChatGPT 是 Planner。请同步 GitHub `main` 后严格执行已推送的 R5.1-R2 安全补验；**严格离线，不允许真实 DeepSeek API 调用或凭据读取**。

## 规范、Issue 与基线

- Repo: https://github.com/yujian777555/ResearchCI
- Issue: https://github.com/yujian777555/ResearchCI/issues/18
- Planner **权威规范**：`docs/PHASE2B_DS1_R5_1_R2_AMENDMENT.md`
- Planner commit：`7f6f68a5f6e537947672254e0587a68fd1828e02`
- R5.1-R1 implementation：`eb333420cf22b6e7f83b03fa9d28dab2efde0dbe`
- R5.1-R1 result HEAD：`7130db6114e2e69b9763267428e344eb406177f3`
- 冻结 DS-0-R1 hash：`sha256:07cc0a68ec471f796dbc312c39f8386b6ff956d64524043adc11632c4bb448fe`
- 冻结 STATS-0-R1 hash：`sha256:e6e262d95c55611f48541637a7ffbb8d75421632324030b52b0dd03477b5a083`

严格以 GitHub 当前文件为准；若本提示词与权威规范冲突，后者优先。开始前 `git fetch; git pull --ff-only; git status; git rev-parse HEAD; git rev-parse origin/main`，只有 main、HEAD==origin/main、clean 方可执行。

## 本轮精确阻断项

**B1：两个 symlink 测试因 WinError 1314 跳过。** 将 symlink、Windows junction/reparse、hardlink、路径遍历、existing summary 和 `*.tmp` collision、fsync/disk/permission fault 测试拆成独立项，不允许 symlink permission 一次 skip 掩盖其他断言。真实 symlink 运行时证据需要有权限的 Windows/Unix 受控 runner；若环境不支持，保留 `LINK_RUNTIME_VALIDATION_PENDING`，不得写 PASS。增加无需创建真实 symlink 的原生句柄/属性注入 fail-closed 测试，同时明确它们只是 SIMULATED。

**B2：`native_evidence.atomic_json` 已存在目标时引用未定义的 `PathIdentity`，后续又调用路径式 `os.replace`；`QualificationGate` 用 `Path.read_text()` 读取安全审计摘要。** 修成明确、可验证的 **不可覆盖一次性结果发布**；使用固定目录句柄、不可猜临时名、原子发布、fsync、安全 read-back、路径与句柄身份核查。禁止依赖意外 NameError 当做拒绝。安全敏感 summary read 使用受保护的 native reader。用行为测试覆盖已存在目标、别名/替换、temp collision、故障时不覆盖/不伪造 PASS。

**B3：v2 `LIVE_HTTP` 正向准入链及拒绝顺序仍缺行为证据。** 在纯离线环境生成临时 v2 RSA key pair、构造合格签名 intent，使用 mock 的无网络 HTTPTransport/工厂行为和 synthetic key callback，真实调用 `execute_replacement_preflight` 的授权与 ledger 逻辑。检验真实 v2 路径与 v1 拒绝、过期、撤销、错误 key ID、run/token/SHA/stage/mode/ledger-path、脏分支/旧远端、重复 token。每个未批准项都应在 credential callback 和 production transport construction 前拒绝，二者计数 0。合法 PRECHECK_ONLY 也必须无法 POST /responses。任何假生产授权、签名私钥或真实 API key 不得提交。

## 限制与交付

只允许 `agentbench/deepseek_live_canary/**`、R5.1-R2 专属离线测试与 **新** `phase2b_ds1_r5_1_r2_*` 报告。保留原始 `FAIL_PREFLIGHT_ARTIFACT`、全部历史 R1–R5.1-R1 报告、DS-0-R1 provider/协议、STATS-0-R1、ResearchCI core、所有科研语义与 benchmark 不变。

运行完整 pytest，报告 pass/fail/skip 的准确数值；不得用伪造跳过原因补齐覆盖。新报告：diagnostic、offline_e2e、regression、scope_audit、harness_freeze、安全审查 MD；覆盖每项测试的 PASS/SKIPPED/SIMULATED/NOT_RUN 与尚存风险。

`git commit -m "Phase 2B-DS-1-R5.1-R2: complete offline native evidence and v2 live gate proof"`，推送 main，核验远端一致、工作区 clean，返回完整 SHA、哈希、测试、scope 和零实际请求证据，然后 **STOP**。

**禁止：** 真实 `GET /models`、真实 `POST /responses`、真实 key/env credential 读取、live canary、pilot、formal、自动关闭 Issue #18。仍未得到人类 live 许可。
