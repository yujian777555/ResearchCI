# Phase 2B-DS-1-R5.1-R3.3 Windows Runtime Security Review

## 范围与基线

- 基线：`c72e844d4cfc998da4b44715bf2aa569447e98de`（`main`，与 `origin/main` 同步）。
- 本轮只验证 `native_evidence`、`secure_io`、审计持久化、summary 原子发布和路径身份保护。
- 未修改授权流程、LIVE_HTTP gate、DeepSeek/STATS protocol、历史科研报告或 `src/researchci/**`。
- 未读取真实凭据，未建立 provider 网络连接，未运行 `/models`、`/responses`、canary 或 benchmark。

## Windows 环境

- OS：Windows 11 家庭中文版，Build 26200（Python `platform` 标识为 `Windows-10-10.0.26200-SP0`）。
- Python：3.10.1，解释器 `C:\Program Files\Python310\python.exe`。
- 身份：`desktop-tvsk9sh\\于舰`。
- `SeCreateSymbolicLinkPrivilege`：未出现在 `whoami /priv`。
- Developer Mode：`DISABLED_OR_NOT_SET`。
- 管理员组提示为真，但本轮未请求提权，也未改变系统策略；不能把组成员资格等同于拥有符号链接权限。

## 测试矩阵

| 场景 | 结果 | 运行时证据 |
| --- | --- | --- |
| audit 文件 symlink | `ENVIRONMENT_BLOCKED` | `os.symlink` 返回 WinError 1314；未修改 outside 文件 |
| summary 文件 symlink | `ENVIRONMENT_BLOCKED` | `os.symlink` 返回 WinError 1314；未修改 outside 文件 |
| 父目录 symlink | `ENVIRONMENT_BLOCKED` | 目录 symlink 返回 WinError 1314 |
| directory junction | `PASS` | `mklink /J` 成功；audit、summary、read-back 均拒绝重解析路径，outside sentinel 不变 |
| reparse point | `PASS` | 真实 junction 的 `FILE_ATTRIBUTE_REPARSE_POINT` 被识别，写入被拒绝 |
| hardlink | `PASS` | 原生 `st_nlink != 1` 拒绝；外部重要文件内容不变 |
| target replacement | `PASS` | 已发布 summary 不可覆盖，原文保持不变 |
| TOCTOU replacement | `PASS` | 证据句柄固定期间 Windows 共享策略阻断替换；未继续写入 |
| permission/fsync failure | `PASS`（故障注入） | 注入 fsync 错误向上返回，未产生成功 summary；这是行为级离线注入，不是 ACL 运行时结论 |
| audit hash chain | `PASS` | 两条事件 append/fsync/read-back，链尾 hash 可复核 |
| summary atomic write/read-back | `PASS` | 原子发布、JSON 读回与内容一致 |
| path identity / traversal | `PASS` | 父路径遍历在写入前拒绝 |

三类真实符号链接由于 WinError 1314 未完成运行时验证；它们在报告中保持 `ENVIRONMENT_BLOCKED`，没有被改写为 PASS。重解析点、junction、hardlink 与句柄替换场景是在目标 Windows 主机上执行的真实文件系统测试。

## 回归

- 命令：`python -m pytest`
- 收集：469
- 通过：467
- 跳过：2（既有 R5.1/R5.1-R1 的符号链接权限测试，均明确记录 WinError 1314）
- 失败：0
- R3.3 新增用例：12 passed

## 审计结论

`native_evidence` 的父目录固定、重解析点/链接拒绝、单文件身份复核、硬链接拒绝、不可覆盖发布和读回校验均通过当前可执行场景。由于当前部署环境不能创建真实文件或目录 symlink，尚不能证明所有 symlink 重定向攻击在该环境中完成运行时闭环。

最终状态：`WINDOWS_RUNTIME_VALIDATION_PENDING`。

`LIVE ACTIVATION BLOCKED` 必须保留，等待 Planner 决定是否在具备受控符号链接权限的目标部署环境重新执行验证。此报告不构成 provider 资格认证或 live canary 授权。
