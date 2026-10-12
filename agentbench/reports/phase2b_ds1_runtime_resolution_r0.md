# Phase 2B-DS-1-RUNTIME-RESOLUTION-R0

## Current Runtime Evidence

### Linux

WSL2 Ubuntu-22.04 使用真实 Linux `/tmp` 文件系统，Kernel 为 `6.18.40.1-microsoft-standard-WSL2`。文件 symlink、summary symlink、TOCTOU replacement、hardlink、父目录替换后的 audit append、summary write 和 evidence publish 均通过；outside target 未修改，audit hash chain 和 summary integrity 保持有效。

### Windows

Windows junction、reparse point 和 hardlink 已通过。文件 symlink、目录 symlink 由于 `SeCreateSymbolicLinkPrivilege` 缺失和 WinError 1314 无法完成；完整 parent replacement 的三个入口受到 WinError 5 句柄共享限制，保持 `ENVIRONMENT_LIMITED`。

## Production Runtime Recommendation

`RECOMMENDED_RUNTIME: Linux`

`RUNTIME_ACCEPTED: Linux`

本轮选定未来一次受控 Provider Preflight 的具体 runtime 为本机已有 **WSL2 Ubuntu-22.04**，Kernel `6.18.40.1-microsoft-standard-WSL2`、UID 1000、`/usr/bin/python3` 3.10.12。evidence 和 ledger 必须位于原生 Linux 文件系统；验证场景发生在 `/tmp`。Windows 挂载目录（例如 `/mnt/c`、`/mnt/d`）不在此次文件系统资格认可范围内。

本轮只读查询确认内核、Python 和用户与原报告一致，`stat -f` 将 `/tmp` 与 `/home/yujian` 都标识为 `ext2/ext3`，设备编号均为 2096。这支持后续在同一原生文件系统上选择持久 audit sink，但未来具体目录仍须验证可写、身份和持久化能力。没有创建生产 sink、transport 或 ledger reservation。

`RUNTIME_ACCEPTED` 仅表示基于本轮规范接受上述环境的文件系统安全证据，提交 Planner 审查。其他 Linux 主机、container、Python 环境或不同文件系统不自动继承这个结论，必须重新确认指纹和资格；本轮没有验证 Provider SDK、连通性或请求资格。

选择 Linux 的原因是 Linux runtime 已完成 symlink、TOCTOU、hardlink、父目录替换、hash chain 和 summary integrity 的真实验证；Windows 仍有 symlink privilege 和完整目录替换证据缺口。

## Security Impact

上述 WSL2 Linux 满足已列出的 evidence integrity、TOCTOU protection 和文件系统 runtime qualification。Windows 仍为 pending，只能作为开发或非生产环境，直到取得真实运行证据。Windows 的限制不再阻断所选 Linux 的文件系统资格；它也没有被标为 Windows PASS 或全平台 RUNTIME_COMPLETE。

Runtime resolution 不改变 authorization decision：当前 decision 仍是 `HOLD`，execution authorization 仍是 `NOT GRANTED`，`LIVE ACTIVATION BLOCKED` 保持不变。没有 Provider 请求、credential callback 或 transport 创建。

剩余执行条件是 Planner 独立批准、批准的 credential source、与 run/repository/protocol 绑定的有效签名授权、一次性 ledger 准入及未来 audit sink 的实际可写证明。选择 Linux 只解决 runtime 路由与文件系统证据范围，不授予一次真实请求。

## 可复核证据

- [Linux 运行报告](phase2b_ds1_r5_1_env_closeout_r1_recheck_linux.json)：8/8 PASS；SHA-256 `182b1931ff6356c1206ea02fcd6f34a2aeb7e4521bf3fee4fb08bc8dbaa28dc7`。
- [Windows 运行报告](phase2b_ds1_r5_1_env_closeout_r1_recheck_windows.json)：2 PASS、6 ENVIRONMENT_BLOCKED；SHA-256 `6e32ddfa840ed4e8d4d3ec01c56268830f2cf3931cdd9eb37c014a4c4812c0aa`。
- [TOCTOU 修复审查](phase2b_ds1_r5_1_secfix_toctou_r1_security_review.md) 与运行报告中的 source_hashes：本轮逐项核对源码字节一致，未修改安全实现。
- [历史 HOLD 决策](phase2b_ds1_live_preflight_authorization_decision_r0.json)：只读保留。

具体证据文件哈希、case id 和当前环境观测记录在本轮 JSON 中。原报告未改写；Linux 测试并未在本轮伪造为新的 runtime 执行结果。
