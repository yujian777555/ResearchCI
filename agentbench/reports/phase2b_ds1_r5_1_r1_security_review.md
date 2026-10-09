# ResearchCI Phase 2B-DS-1-R5.1-R1 Security Review

状态：`READY_FOR_PLANNER_REVIEW`

修复内容：

- 证据 append/read 和 summary publish 已转入 native handle 层，拒绝路径遍历、symlink/reparse、可预测临时文件和文件身份替换；append hash chain 使用 fail-closed 文件锁与 fsync。
- LIVE_HTTP 在 verifier、cutover 和 SDK factory 三层强制 schema v2 公钥授权；legacy v1 在凭据回调和生产 transport 构造前拒绝。
- SQLite ledger 保持 FULL transaction、外部 claim tombstone、单向状态和 UNKNOWN restart 语义。

验证限制：当前 Windows token 不允许创建 symlink，2 项 symlink 测试 skip（WinError 1314）；代码路径仍 fail-closed，未声称该平台已实际生成 symlink 样本。管理员/内核级本机攻击、Git 服务器身份和真实 provider 兼容性不在本轮威胁模型内。

本轮未读取真实 API Key、未访问 provider 网络、未运行 live canary/benchmark，不构成 LIVE_AUTHORIZED。
