---
slug: studio/llm-module
title: LLM Module 设计
order: 53
summary: 统一调用、可观测与可复盘。
---

# LLM Module 设计

目标：让所有 LLM 调用具备统一入口、可追溯的 prompt 记录、可复盘的输出。

## 设计原则

- 统一入口：所有 LLM 调用集中走 `src/fomc/infra/llm.py`
- Prompt 外置：研报与会议模拟的 prompt 以 Markdown 模板维护
- 可观测性：每次调用写入 `data/prompt_runs/`，可回放输入与输出
- 轻量化：不引入 LangChain 等框架，保持简单可控

## 调用入口

核心客户端：`src/fomc/infra/llm.py`

- `LLMClient.chat(...)`：DeepSeek/OpenAI 兼容接口
- 内置超时、重试与退避
- 统一读取 `.env` 配置

关键环境变量：

- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_MODEL`
- `DEEPSEEK_TIMEOUT`
- `DEEPSEEK_RETRIES`

## Prompt 组织与渲染

研报与宏观月报：

- `content/prompts/reports/`  
  - `nfp_report.md` / `cpi_report.md` / `macro_monthly_report.md`
  - 多智能体模板：`report_consistency.md` / `report_completeness.md` / `report_logic.md` / `report_editor.md`

会议模拟：

- `content/prompts/meetings/`  
  - blackboard / stance / speech / questions / packages / vote / secretary / statement+minutes

模板结构：

- frontmatter 中包含 `prompt_id` / `prompt_version` / `system_prompt`
- 文件正文是 user prompt，使用模板变量注入结构化数据

## 可观测与日志

每次调用会记录到 `data/prompt_runs/`：

- NFP/CPI 研报：`data/prompt_runs/nfp/` / `data/prompt_runs/cpi/`  
- 宏观月报：`data/prompt_runs/macro/`  
- 会议模拟：`data/prompt_runs/meetings/`

日志内容包含：system/user prompt、输出文本、模型参数、角色与时间戳。  
多智能体链路会把每个 agent 的输入与输出写入同一运行日志文件。

## 输出约束与一致性

- 明确禁止编造：system prompt 中强约束“不得引入未提供数据”
- 缺失声明：输入缺失时强制显式说明
- 结构化输出：会议模拟采用 JSON schema 输出

## 未引入的能力（暂不需要）

- LangChain 复杂链式调度  
- Agent 工具调用与长期记忆  
- 向量检索统一层

当前需求集中于研报与会议模拟的稳定输出，因此保持轻量。
