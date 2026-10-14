# Phase 2B-DS-1-LIVE-PREFLIGHT-GRANT-REISSUE-R1

## Reissue result

本轮生成的 Grant 自身绑定当前 main HEAD：`3489ed40af3589313f2d3c5a08d9da5faf41dddf`，scope 固定为 DeepSeek `GET /models`、最多 1 request，credential source 仍为 lazy `environment_callback`，且没有获取或调用 callback。

旧 Grant 的目标是 `1fa9b1958993c9a89c6001036ead6fdb88064c28`，已标记为 `REJECTED_STALE`。

## Binding audit

当前 Grant 的自身 SHA 校验通过，但现有依赖工件仍绑定旧提交：

- execution config：`62c5eb67ecde46b5204b7581c20a1542273dbf67`
- execution auth：`25e9dfccaaf7cf0113746070db16da3b06efe89a`
- approval/readiness：`1fa9b1958993c9a89c6001036ead6fdb88064c28`

因此完整链不是同一个 immutable target，链状态为 `STALE_DEPENDENCIES`，Grant 保持 `HOLD`，execution 保持 `BLOCKED`。本轮没有伪造依赖工件已刷新。

## Scope and credential boundary

唯一允许的未来 scope 是 DeepSeek `GET /models`、最多 1 request。`POST /responses`、其它 endpoint、tool/agent execution、benchmark、canary 和自动重试均拒绝。

credential 只登记 `DEEPSEEK_API_KEY` 引用；本轮未读取环境变量、未调用 callback、未获取 credential value、未创建 transport。

## Offline evidence

测试覆盖当前 HEAD 自身绑定、旧 Grant 拒绝、mixed chain 拒绝、scope mutation 拒绝和 callback 计数为 0。真实 Provider、网络、credential、canary 和 benchmark 计数均为 0。

## Regression

R1 离线测试：9 passed。全量 `python -m pytest -q` 收集 630 项，536 passed、90 failed、4 skipped；失败集中在既有 Windows `native_evidence.evidence_lock` 锁文件打开路径（`WinError 80` 后继 `WinError 5`），没有修改冻结安全核心。结果标记为 `ENVIRONMENT_BLOCKED`，不能宣称全量回归通过。

## Scope

本轮仅新增 Grant reissue 工件和离线测试。现有 execution config/auth/approval 的旧 SHA 被保留并标为链阻断；没有伪造它们已刷新。真实 Provider API、网络、credential、callback、canary 和 benchmark 计数均为 0。
