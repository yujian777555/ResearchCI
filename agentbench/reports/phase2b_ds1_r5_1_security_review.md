# ResearchCI Phase 2B-DS-1-R5.1 Security Review

状态：`READY_FOR_PLANNER_REVIEW`

## 已验证

- 远端新鲜度：`git ls-remote origin refs/heads/main` 与本地 `HEAD`、`origin/main`、分支、clean worktree 比对；transport 前重新检查。
- 授权：R5.1 v2 公钥签名路径绑定 `key_id`、有效期、撤销集合、run/token、harness SHA、transport mode、`PRECHECK_ONLY` 和 ledger 路径。执行器没有签发入口或环境变量回退。
- 账本：SQLite `FULL` 同步事务、唯一 token/run/hash、hash-chain、外部 claim tombstone、单向状态转换；跨进程 16 竞争仅 1 个赢家。
- 故障：audit append/fsync、summary 写入、timeout/connection、HTTP_STARTED 崩溃、结果未知均拒绝自动重试。
- 传输：同一 R4 SDK factory；`HTTPTransport` 仅有 v2 reservation 才可构造，`max_retries=0`、transport retries=0、TLS、`trust_env=False`、无重定向、900 秒超时。
- 文件：仓库外 ledger/evidence 路径拒绝遍历、链接/reparse point；POSIX 使用 owner-only 权限，Windows 应用 owner + SYSTEM ACL；敏感值不写入 audit/summary。

## 剩余风险与威胁边界

1. 本机拥有管理员/进程注入能力的攻击者可同时替换 SQLite、claim tombstone、源码和信任锚；R5.1 不声称能防御受控主机攻击。
2. Git 远端新鲜度依赖 Git 传输层及其服务器认证；R5.1 不额外实现 GitHub 独立公钥见证。
3. R5.1 没有读取真实凭据或访问真实 provider，因此不能证明 DeepSeek 认证、账户余额、模型可用性或远端 Responses 兼容性。
4. 当前有效 v2 线上授权必须由独立操作者产生；仓库只包含离线 synthetic fixtures，不包含可用生产授权。
5. 任何 ledger/audit/summary 持久化不确定均进入 `UNKNOWN`，不允许转换为 PASS 或启动 canary。

测试限制：当前 Windows 执行环境未授予创建 symlink 的权限，因此 symlink 替换测试被 pytest skip；代码路径检查仍以 fail-closed 实现，实际 symlink/reparse 运行时未在本机生成样本。

## 结论

R5.1 具备提交 Planner 代码审查的条件；不构成 `LIVE_AUTHORIZED`，不批准 replacement `GET /models`、`POST /responses`、live canary 或 benchmark。
