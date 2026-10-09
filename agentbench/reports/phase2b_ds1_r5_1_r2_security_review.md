# ResearchCI Phase 2B-DS-1-R5.1-R2 Security Review

状态：`READY_FOR_PLANNER_REVIEW`

已修复：

- evidence append/read 与 summary publish 统一使用 native pinned-handle path；summary 已发布目标不可覆盖，临时文件随机且独占，现有 predictable `.tmp` 会拒绝。
- QualificationGate summary read-back 改用受保护 native reader。
- LIVE_HTTP 在凭据回调和生产 transport 构造之前强制 v2 public-key authorization；legacy v1 只能用于 MOCK_HTTP 离线兼容。
- B1/B2 故障注入、受保护读写和入口顺序均有行为测试。

明确限制：

- 当前 Windows token 不允许创建 symlink，两个 on-disk symlink 测试为 `SKIPPED`，状态为 `LINK_RUNTIME_VALIDATION_PENDING`；没有将 skipped 记为 PASS。模拟属性/路径拒绝已测试。
- R2 未读取真实 API Key、未访问真实 provider、未进行 live canary。
- 管理员/内核级本机攻击和真实 GitHub/provider 身份验证不在本轮威胁模型内。

结论：R2 可提交 Planner 审查，不构成 LIVE_AUTHORIZED。
