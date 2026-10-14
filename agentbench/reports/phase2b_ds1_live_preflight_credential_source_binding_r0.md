# Phase 2B-DS-1-LIVE-PREFLIGHT-CREDENTIAL-SOURCE-BINDING-R0

## 目标

本轮只绑定未来允许使用的 credential 来源，不获取 credential value。来源引用为 `DEEPSEEK_API_KEY`，但本轮没有读取环境变量、枚举环境、调用 callback 或保存任何凭据材料。

## Source binding

- Provider：DeepSeek
- source type：`environment_callback`
- source reference：`DEEPSEEK_API_KEY`
- acquisition：`callback_only`、lazy、one-shot；只有显式授权后才允许调用
- 当前状态：`SOURCE_REGISTERED`
- credential：`NOT_ACQUIRED`

来源引用不是凭据本身。绑定阶段不扫描环境，也不判断该引用是否存在。

## Callback contract

未来 callback 只能在 `AUTHORIZED_TO_ACQUIRE` 状态调用，并将 opaque material 保存在内存中。不得枚举环境、写磁盘、写日志、写 evidence、写 summary 或写异常消息。请求完成、失败、超时、中止、异常或销毁失败时都必须销毁；失败语义为 `UNKNOWN`，禁止自动重试。

允许的唯一 scope 是 DeepSeek `GET /models`、最多 1 request。`POST /responses`、其它 endpoint、tool/agent execution、benchmark 和 canary 均被拒绝。

## State machine

`SOURCE_REGISTERED → AUTHORIZED_TO_ACQUIRE → ACQUIRED → CONSUMED → DESTROYED`。

本轮只能停留在 `SOURCE_REGISTERED`。`SOURCE_REGISTERED → ACQUIRED`、销毁后重新获取、消费后重新获取均非法。

## Offline evidence

离线测试覆盖：模拟来源存在但不获取、自动扫描拒绝、callback 调用计数为 0、持久化和日志写入拒绝、scope 固定、生命周期重用拒绝及报告 secret scan。所有真实 Provider、网络、credential、canary 和 benchmark 计数均为 0。

Execution status 仍为 `BLOCKED`；本工件不会将 Grant 转为 `GRANTED`。

## Regression

来源绑定离线测试：10 passed。全量 `python -m pytest -q` 收集 611 项，517 passed、90 failed、4 skipped；失败集中在既有 Windows `native_evidence.evidence_lock` 锁文件打开路径（`WinError 80` 后继 `WinError 5`），没有修改该冻结安全核心。该结果标记为 `ENVIRONMENT_BLOCKED`，不能宣称全量回归通过。

## Scope

本轮仅新增来源绑定工件和离线测试；授权、secure IO、native evidence、ledger、协议、科研代码与历史报告均未修改。真实 Provider API、网络、credential、callback、canary 和 benchmark 计数均为 0。
