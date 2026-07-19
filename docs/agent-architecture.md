# 自定义 Agent 架构

## 目标

项目内 Agent 用于 CI 失败分析、日报生成和 Commit 分析。它采用单 Agent ReAct 执行模型，业务服务只提交任务，不直接依赖 Smolagents 的返回结构。

## 分层

1. **业务接入层**：`failure_analysis.py`、`daily_summary.py`、`commit_analysis_summary.py` 构造 `AgentTask`，并统一检查 `AgentResult.exit_code`。
2. **执行编排层**：`agent_service.py` 负责参数校验、模型适配、技能与记忆注入、工具选择、超时中断、结果清洗和指标采集。
3. **能力层**：`skill_registry.py` 从内置目录和数据目录加载技能；数据目录技能可覆盖同名内置技能。
4. **工具边界层**：`agent_tools.py` 只提供只读文件、记忆检索和 GitHub API。没有 shell、写文件或删除能力。
5. **记忆层**：`memory_manager.py` 保存结构化分析结果，并以标签、标题、摘要和正文综合排序召回。

## 执行流程

```text
业务请求 -> AgentTask 校验 -> 召回历史记忆 -> 加载技能提示词
        -> 选择最小工具集 -> 创建模型与 Agent -> ReAct 循环
        -> 清洗输出 -> 保存记忆 -> AgentResult
```

## 可靠性约束

- `max_steps` 限制为 1–100，单次执行超时限制为 1–7200 秒。
- 超时后调用 Smolagents 的中断接口，并返回退出码 `124`。
- 每次运行使用独立 `ContextVar` 工具上下文，结束后恢复，防止并发任务串用 token 或数据库会话。
- 文件路径通过解析后的父子关系校验，不能逃逸 `DATA_DIR`；正则和文件大小均有限制。
- GitHub 工具只接受 `https://api.github.com:443`。
- Agent 错误以结构化结果返回；调用方不得把空内容当成成功结果持久化。

## 扩展方式

- 新增场景时先增加技能目录及 `scope`，再在 `_select_tools` 中配置最小工具集。
- 新工具必须保持只读、输入有上限、输出截断，并明确网络或文件访问白名单。
- 新记忆类型应使用稳定的 `memory_type` 和可过滤的 metadata，避免把易变文本作为过滤键。

