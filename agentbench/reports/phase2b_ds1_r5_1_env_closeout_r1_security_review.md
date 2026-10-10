# Phase 2B-DS-1-R5.1-ENV-CLOSEOUT-R1 安全审查

## 环境与基线

- 基线：`e276934df2149ca5b2b74ae077daa48225cfb869`，`main` 与远端同步。
- Windows：Windows 11 家庭中文版，Build 26200，Python 3.10.1。
- 用户：`desktop-tvsk9sh\\于舰`。
- `SeCreateSymbolicLinkPrivilege`：未授予。
- Developer Mode：未启用。
- 本轮未修改注册表、组策略或系统策略。
- WSL2 Linux 既有 harness：Kernel `6.18.40.1-microsoft-standard-WSL2`，Python 3.10.12，8/8 场景通过。

## Windows 真实运行矩阵

| 测试 | 结果 | 证据 |
| --- | --- | --- |
| 文件 symlink | `ENVIRONMENT_BLOCKED` | Python `os.symlink` 返回 WinError 1314；`mklink` 报告无足够权限 |
| 目录 symlink | `ENVIRONMENT_BLOCKED` | Python directory symlink 返回 WinError 1314；`mklink /D` 同样被拒绝 |
| 父目录替换 | `PASS` | 真实 rename/replace 尝试完成；pinned parent identity 检测到变化并拒绝，outside 未写入 |
| Junction | `PASS` | R3.3 真实 `mklink /J` 证据保留 |
| Reparse point | `PASS` | R3.3 真实 `FILE_ATTRIBUTE_REPARSE_POINT` 证据保留 |
| Hardlink | `PASS` | R3.3 真实 hardlink 被拒绝，外部文件不变 |

## Linux 既有验证

WSL2 `/tmp` 真实 Linux 文件系统 harness 通过：

- symlink：PASS
- TOCTOU：PASS
- hardlink：PASS
- parent replacement：PASS
- permission failure：PASS
- audit hash chain：PASS
- summary atomic read-back：PASS

## 结论

当前代码安全行为在 Linux 真实文件系统和 Windows 可执行场景中没有新增缺陷。Windows 文件和目录 symlink 仍不能取得真实运行证据：Python 和 `mklink` 都受到 WinError 1314/权限策略阻断。因此不能把环境阻断升级为 PASS。

最终状态：`WINDOWS_RUNTIME_VALIDATION_PENDING`。

`LIVE ACTIVATION BLOCKED` 保持不变，等待具备受控 Windows symlink 能力的部署环境重新执行；本报告不构成 Provider 资格认证或 live 授权。

## 回归

- `python -m pytest -q`
- 476 collected
- 472 passed
- 4 skipped
- 0 failed，0 errors

4 个 skip 均有明确原因：两个既有 symlink 权限测试，以及两个 R1 symlink/父目录替换测试的 Windows 环境限制。
