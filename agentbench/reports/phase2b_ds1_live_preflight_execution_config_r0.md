# Phase 2B-DS-1-LIVE-PREFLIGHT-EXECUTION-CONFIG-R0

## Execution Boundary

未来配置只允许一个动作：DeepSeek `GET /models`，最多 1 request。POST、tool calls、agent tasks、benchmark 和 canary 均禁止。配置冻结不代表执行授权。

## Binding

配置绑定到 Linux WSL2 Ubuntu-22.04 原生 Linux filesystem、当前 repository SHA、DeepSeek/STATS protocol hashes，以及 Final Approval → Execution Authorization → Grant 链。任一 SHA、hash、runtime、approval、grant 或 scope 变化都会使配置失效。

## Credential Boundary

credential 只能通过 approved callback source 进入 memory，不能持久化，request 完成后销毁。当前 credential 为 NOT PROVIDED，未调用 callback。

## Current State

配置文件本身是完整的参数组合，但状态为 `BLOCKED`：Grant 为 HOLD，Execution Authorization 为 NOT GRANTED，Credential 为 NOT PROVIDED。因此不能进入 READY，也不能构造 transport 或执行请求。

状态约束为 `CONFIG_CREATED → VALIDATED → READY`；`BLOCKED`、`INVALID` 和 `EXPIRED` 是失败状态，禁止从 BLOCKED 进入 EXECUTE。

本轮没有 Provider 请求、HTTP、socket、credential acquisition、canary 或 benchmark。`LIVE ACTIVATION BLOCKED` 保持不变。
