# Phase 2B-DS-1-LIVE-PREFLIGHT-EXECUTION-PLAN-R0

本文件定义未来一次受控 Provider preflight 的执行程序。本轮没有执行请求、创建 transport、读取凭据或连接网络。

## Runtime Binding

执行 runtime 固定为已验证的 **WSL2 Ubuntu-22.04 Linux**：Kernel `6.18.40.1-microsoft-standard-WSL2`，Python 3.10.12，evidence 必须位于原生 Linux filesystem。Windows filesystem、未验证 mount 和 network filesystem 不在执行范围内。其他 Linux 主机或容器必须重新做 runtime qualification。

## Pre-execution Checklist

Executor 只有在以下检查全部通过后才能进入 reservation：

- environment：runtime identity、repository SHA、protocol hashes、filesystem qualification、clock/time validity
- authorization：approval artifact、签名、scope、expiry 和 revocation
- ledger：one-use reservation 可用
- credential：批准的 callback source；不读取 disk secret，不导出 environment，不记录敏感值

任何检查失败都停止，不能构造 transport。

## Execution Sequence

1. 启动已批准的 Linux runtime。
2. 验证 repository freshness。
3. 验证 authorization artifact 和 scope。
4. 消费一次性 ledger reservation。
5. 通过批准的 callback 临时获取 credential。
6. 构造 production transport。
7. 严格执行一次 `GET /models`。
8. 持久化 evidence。
9. 销毁内存中的 credential material。
10. 停止。

## Hard Limits

请求方法固定为 `GET`，endpoint 固定为 `/models`，最多 1 request。`POST /responses`、chat completion、tool calls、agent execution、benchmark 和 canary 立即拒绝。

## Abort Conditions

repository mismatch、protocol mismatch、filesystem failure、授权过期、撤销、scope 改变、unexpected endpoint/method、redirect、retry request、audit write failure 或 summary persistence failure，均立即停止并将结果标为 `UNKNOWN`。UNKNOWN 不重试、不重新 reservation、不继续执行。

## Post-execution Evidence

允许保存 run id、authorization fingerprint、repository SHA、protocol hash、request metadata、response metadata 和 final state。credential、secret、authorization header 和 raw token 禁止写入 evidence。audit hash chain、atomic summary 和 read-back 必须通过；credential material 在 evidence 持久化后销毁。

当前 execution authorization 仍为 `NOT GRANTED`，`LIVE ACTIVATION BLOCKED`。本计划只说明 Planner 未来批准后如何执行，不能替代批准本身。
