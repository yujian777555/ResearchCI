# Phase 2B-DS-1-LIVE-PREFLIGHT-CREDENTIAL-PROVISION-R0

本轮定义未来一次受控 Provider preflight 的 credential 生命周期。没有读取实际 credential，没有调用 callback，没有创建 transport，也没有网络请求。

## Lifecycle

状态路径为：

`CREATED → IN_MEMORY → CONSUMED → DESTROYED`

如果请求在消费前中止，也可从 `IN_MEMORY` 进入 `DESTROYED`。`DESTROYED` 不能回到 `IN_MEMORY` 或 `CONSUMED`，`CONSUMED` 不能回到 READY。生命周期最多持续 900 秒。

凭据只允许通过获批准的 execution grant callback 进入内存；执行一次请求后立即销毁引用。request completed、request failed、timeout、abort、exception 和 destroy failure 都触发销毁路径。

## Storage and Leakage Boundary

生命周期使用 `callback_only` 和 `memory_only`。禁止写入 disk、database、logs、audit、summary、reports、git 或 exception message；evidence 只保存状态、指纹和 metadata，不保存 credential material。

## Scope Binding

credential 只能绑定 DeepSeek `GET /models`，最多 1 request。POST、chat completion、tool execution、benchmark 和其他 endpoint 变更均拒绝。

## Failure Semantics

callback failure、partial acquisition、transport uncertainty、destroy failure 和 unexpected exception 均产生 `UNKNOWN`。禁止 automatic retry、再次 reservation 或复用已销毁对象。

## Current Status

当前 credential 为 `NOT PROVIDED`，execution authorization 为 `NOT GRANTED`，`LIVE ACTIVATION BLOCKED`。这个设计回答了未来允许执行时如何让 credential 进入内存、只使用一次并在所有退出路径消失；它不构成 credential 提供或执行批准。
