# ResearchCI Phase 2A AgentBench

这是本地 scripted harness 的冻结输入目录。它包含 6 个压力族在 3 个受控科学 profile 上的 18 个情景、版本化 prompt、agent 可见 tool schema、独立 evaluator metadata 和 workspace 起始文件。

Phase 2A-R1 的实际 agent context 使用不编码压力族的 opaque episode ID；condition、family、target rule/stage 只保存在 harness-owned metadata。Phase 2A 不调用真实 LLM/Agent，不进行网络访问。

运行：

```text
python -m researchci_agent run-scripted --root agentbench --output agentbench/reports
```
