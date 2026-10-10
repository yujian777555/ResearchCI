# Phase 2B-DS-1-R5.1-ENV-AUDIT 安全审查

## 基线与范围

- 基线：`b3e5338f5045686c60db42f322147cb57b0aeac7`，`main` 与 `origin/main` 同步。
- 本轮使用 WSL2 Ubuntu 22.04 的真实 Linux `/tmp` 文件系统执行链接攻击测试，并保留 Windows R3.3 证据。
- 未修改 `authorization.py`、`cutover.py`、`sdk_client.py`、`native_evidence.py`、`secure_io.py`、ledger、DeepSeek/STATS protocol、科研核心代码或历史报告。
- 未读取真实 API key，未建立 provider 网络连接，未运行 `/models`、`/responses`、canary 或 benchmark。

## 环境

### Linux（本轮真实运行）

- OS：Linux（WSL2）
- Kernel：`6.18.40.1-microsoft-standard-WSL2`
- Python：3.10.12，`/usr/bin/python3`
- UID/EUID：1000/1000，用户 `yujian`
- Symlink capability：可用
- 临时目录：Linux `/tmp`，不是 mock path 或字符串模拟

### Windows（R3.3 已保留证据）

- Windows 11 家庭中文版，Build 26200，Python 3.10.1
- `SeCreateSymbolicLinkPrivilege`：不可用
- Developer Mode：未启用
- 文件/目录 symlink：WinError 1314，`ENVIRONMENT_BLOCKED`
- Junction、reparse point、hardlink 和句柄共享替换：已通过 R3.3 运行时验证

## Linux 真实运行矩阵

| 测试 | 结果 | 证据 |
| --- | --- | --- |
| audit 文件 symlink | `PASS` | 真实 symlink 被拒绝，outside 内容不变 |
| summary symlink | `PASS` | 原子写入拒绝真实 symlink，outside 内容不变 |
| 父目录 symlink | `PASS` | 父路径校验拒绝真实 symlink |
| TOCTOU target replacement | `FAIL` | 目录句柄已固定后，将目标替换为普通文件；随后 open 成功，未检测身份变化 |
| hardlink | `PASS` | 单链接约束拒绝 hardlink，外部文件不变 |
| permission failure | `PASS` | 真实只读审计文件返回 `PermissionError`，内容不变 |
| audit hash chain | `PASS` | 两条真实 append/fsync/read-back 事件链可复核 |
| summary atomic read-back | `PASS` | 真实原子发布和 JSON 读回一致 |

## 阻断缺陷

Linux TOCTOU 用例发现 `PinnedDirectory.open()` 在路径检查和文件打开之间没有保留并比较目标的预期身份。攻击者将已检查目标替换为另一个普通文件后，打开路径得到替换对象，`validate_file()` 只比较“打开对象”和“当前路径对象”，二者相同，因此没有 fail-closed。

该结果分类为：

`BLOCKED_SECURITY_DEFECT`

本轮没有修改冻结安全逻辑，也没有将失败改写为 PASS。Planner 需要先决定修复范围和新的回归要求；在此之前不得解除 `LIVE ACTIVATION BLOCKED`。

## Windows 证据与最终判断

Windows symlink 仍因 WinError 1314 无法完成真实运行时验证，状态保持 `ENVIRONMENT_BLOCKED`。即使 Linux symlink、hardlink 和权限场景通过，TOCTOU 的真实安全失败也足以阻止整体验证。

最终状态：`WINDOWS_RUNTIME_VALIDATION_FAILED`。

## 回归

- 命令：`python -m pytest -q`
- 收集：469
- 通过：467
- 跳过：2（既有 Windows symlink 权限测试，WinError 1314）
- 失败：0

回归通过不抵消上述运行时安全缺陷；它只证明现有测试集没有回归失败。
