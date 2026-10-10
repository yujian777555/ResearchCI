# ResearchCI Phase 2B-DS-1-R5.1-R3 Security Review

状态：`READY_FOR_PLANNER_REVIEW`

- v2 正向准入链已通过真实 `execute_replacement_preflight`、临时 RSA 签名、临时 ledger、synthetic credential 和无网络 MockTransport：一次 reservation、一次凭据回调、一次 factory、一次 GET /models、零 POST /responses。
- v2 非法矩阵在凭据回调与 factory 前拒绝；legacy v1 LIVE_HTTP 也在 verifier 入口拒绝。
- 历史报告在 R1/R2 发生的改动由 append-only provenance manifest 记录 Git blob SHA；R3 未覆盖历史报告。
- Windows symlink/junction 运行时样本仍因 WinError 1314 未执行，状态为 `LINK_RUNTIME_VALIDATION_PENDING`；不得将其视为 PASS。Linux/受权 Windows lane 仍需 Planner 后续决定。
- 本轮未读取真实密钥、未访问 provider、未运行 canary/benchmark。

剩余威胁：管理员/内核级本机攻击、Git server authentication、真实 provider 兼容性不在当前威胁模型内。
