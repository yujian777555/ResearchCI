# Phase 2B-DS-1-LIVE-PREFLIGHT-BINDING-REISSUE-R0

## Reissued Binding

启动检查发现实际 `main` 和 `origin/main` 为：

`1fa9b1958993c9a89c6001036ead6fdb88064c28`

这是当前 immutable repository SHA。本轮将 execution config、execution auth、grant reference 和 approval reference 的绑定统一到该 SHA。指令中给出的 `2c6e702` 已是旧提交，不能继续作为当前绑定。

## Scope

唯一 scope 是 DeepSeek `GET /models`，最多 1 request。POST、tool call、benchmark 和 agent execution 仍禁止。DeepSeek/STATS protocol hashes 保持原冻结值。

## Binding Result

- Execution config：`BOUND_CURRENT_HEAD`
- Execution auth：`BOUND_NOT_GRANTED`
- Grant：`HOLD`
- Approval：`HOLD`
- All artifact SHA match：PASS
- Old SHA：REJECT
- Mixed chain：REJECT

重新绑定只是修复 artifact identity consistency；它不把 Grant 转成 GRANTED，也不读取 credential。当前 execution status 是 `BLOCKED`，credential 为 `NOT_PROVIDED`，`LIVE ACTIVATION BLOCKED` 保持不变。

## Current Blockers

- credential source 未提供
- Planner execution approval 未提供
- Grant 仍为 HOLD
- 旧 artifact 不得用于当前 HEAD
