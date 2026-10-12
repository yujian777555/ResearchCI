# ENV-CLOSEOUT-R1 补充运行时证据审查

这份补证建立在 `e276934df2149ca5b2b74ae077daa48225cfb869` 的冻结安全实现上，保留原有 closeout 报告和 Windows 1314 证据不变。

WSL2 Ubuntu 22.04 的真实 `/tmp` 文件系统完成 8 个场景，全部 PASS：文件 symlink、summary symlink、父目录 symlink、TOCTOU 替换、hardlink、父目录替换后的 audit append、summary write、evidence publish。三个父目录场景都实际把原目录重命名并安装 attacker 目录，随后由 pinned directory identity 检查拒绝；原 evidence hash chain、summary 内容保持不变，attacker 目录没有写入。

Windows 补证执行了同一组入口：文件/summary/目录 symlink 均真实尝试失败，Python 返回 WinError 1314，`mklink` 返回 “You do not have sufficient privilege”；junction 和 hardlink 真实 PASS。三个父目录替换场景都尝试在已固定目录句柄后重命名目录，Windows 返回 WinError 5（Access Denied），因此分类为 `ENVIRONMENT_LIMITED`，没有将其写成 PASS。

Windows 既有回归为 476 collected、472 passed、4 skipped、0 failed。补证 harness 自身禁止读取 DeepSeek/OpenAI 凭据并禁止 socket 外连；计数均为 0。WSL 环境未安装 pytest，因此只报告直接执行的 8/8 harness 结果，不伪造 Linux pytest 统计。

原 closeout 报告中的 parent replacement PASS 只覆盖了空目录替换；本补证覆盖完整的 append、summary write 和 publish 入口，结论以本补证为准。Windows symlink 与父目录完整攻击模型仍缺少目标部署环境的权限级运行证据，最终状态保持 `WINDOWS_RUNTIME_VALIDATION_PENDING`，`LIVE ACTIVATION BLOCKED`。
