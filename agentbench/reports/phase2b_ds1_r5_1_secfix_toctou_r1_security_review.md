# Phase 2B-DS-1-R5.1-SEC-FIX-TOCTOU-R1 安全审查

## 原始漏洞

ENV-AUDIT 在 Linux 真实文件系统中发现：路径检查完成后，攻击者可以在文件打开前把目标替换为另一个普通文件。旧实现随后把“打开对象”和“当前路径对象”进行比较；两者都已经指向替换对象，因此比较通过并继续写入，未满足 `checked identity == opened identity`。

历史失败证据保留在 `phase2b_ds1_r5_1_env_audit.json`，本轮没有改写或删除。

## 修复方法

修改 `native_evidence.PinnedDirectory.open()`：

1. 父目录先以目录 fd 固定。
2. 对已存在目标在打开前保存 `expected` 的 lstat/openat 身份。
3. POSIX 使用相对父目录 fd 的 `os.open(..., dir_fd=parent_fd)`，并带 `O_NOFOLLOW | O_CLOEXEC`。
4. 打开后立即对 fd 做 `fstat()`，比较 device、inode、文件类型和 mode；不一致立即关闭 fd 并 fail closed。
5. 后续写入、fsync、发布和读回都继续使用已验证 fd。
6. Windows 既有 `CreateFileW(OPEN_REPARSE_POINT)`、junction/reparse、hardlink 和共享策略路径保持不变；新增比较只会拒绝身份变化。

这消除了 `stat(path) -> race -> open(path)` 直接作为安全边界的问题：race 后打开的是替换对象时，fd 身份与预期快照不一致，操作被拒绝。

## 修复前后行为

| 场景 | 修复前 | 修复后 |
| --- | --- | --- |
| 普通文件在检查后被替换 | 替换对象可通过当前路径比较并继续 | fd 与 expected 身份不一致，拒绝 |
| inode/device/type/mode 改变 | 仅当前路径对象比较可能漏检 | `_file_identity` 比较失败，拒绝 |
| symlink 替换 | 依赖后续路径检查 | `O_NOFOLLOW`/原生 reparse 检查拒绝 |
| hardlink | `_plain(st_nlink != 1)` 拒绝 | 保持拒绝 |
| 父目录替换 | 固定目录身份检查 | 保持拒绝 |
| summary 发布竞争 | 不覆盖已有目标 | publish 前后目标不可覆盖且读回校验保持 |

## 验证结果

### WSL2 Linux 真实 harness

在 `/tmp` 真实 Linux 文件系统运行 8/8：audit symlink、summary symlink、父目录 symlink、TOCTOU 注入替换、hardlink、只读权限、hash chain、summary atomic read-back，全部 PASS。

WSL Python 环境没有安装 pytest，因此没有伪造 Linux pytest 结果；Linux 结果来自直接执行冻结 native evidence 的真实 harness。

### Windows pytest

- `python -m pytest -q`：476 collected，472 passed，4 skipped，0 failed。
- R1 新增测试：5 passed，2 skipped。
- 两个 R1 skip 明确为 `NOT_RUN`：Windows symlink 权限不可用；父目录替换被原生句柄共享策略阻断。
- 既有 Windows junction、reparse、hardlink、permission、fsync、summary 和 hash-chain 测试继续通过。

## 不变量

- outside target modified：false（Linux/Windows hardlink、symlink、summary 场景）
- audit hash chain：valid
- summary integrity/read-back：valid
- credential callback：0
- provider network calls：0
- live canary / benchmark episodes：0

## 协议与范围

DeepSeek protocol 与 STATS protocol 哈希保持不变；未修改授权、cutover、SDK、ledger、科研核心或历史实验报告。修复只触及 native evidence 身份验证、相关安全测试和 R1 报告。

结论：离线安全修复完成，提交 Planner 审查；真实 provider 与 live activation 仍保持禁止。
