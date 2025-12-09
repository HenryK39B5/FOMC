# 宏观事件处理与 LLM 作用说明

## 总览
- 目标：按月收集高信号宏观新闻，生成事件列表与月度研报。
- 入口：`ensure_month_events(month_key)` / Web 表单。
- 数据源：DDGS `news()`（字段：title, url, source, date, body/snippet, image 等）。
- 存储：SQLite (`months`, `events`, `raw_articles`)，路径 `data/macro_events.db`。

## 流程拆解
1) **多轮搜索**
   - 关键词模板覆盖：劳资/就业、贸易/关税/制裁/工业政策、供应链航道、能源、金融稳定、地缘冲突、公共卫生、全局宏观冲击等。
   - 每轮附月份提示（如 “August 2024”），`max_results` 80，粗时间过滤到目标月。
2) **重要性判断 + 正文抓取（LLM参与）**
   - LLM 读取本轮所有结果（标题+来源），挑选 PRIMARY 链接（默认 <=12）→ 抓正文。
   - SUPPLEMENTARY 保留 DDGS 摘要/片段，不抓正文。
   - 原文入库：`raw_articles` 存 snippet/full_text/domain。
3) **过滤与打标签**
   - 时间过滤到当月；URL 去重。
   - 规则打标签：宏观冲击类型（trade_tariff/sanctions/supply_chain/labor_dispute/financial_stability/other）、影响通道（inflation/employment/growth/financial_conditions）、国家猜测。
   - PRIMARY 事件描述优先使用正文，SUPP 用 snippet。
4) **聚类 → 事件**
   - 按 (date, shock_type) 聚合，多来源形成一个“事件”；重要性 = 来源数量 + 优质域名加权。
   - 结果集上限：自适应筛选 + 全局 cap（默认 20）。
5) **事件级摘要（LLM参与）**
   - 每个事件调用 LLM 生成中文摘要（正文/摘要为输入），并用 LLM 再次排序/筛选（保留约 5–12 条）。
6) **月报生成（LLM参与）**
   - 输入：事件列表 + 来源链接。
   - 输出：Markdown 多段月报，首段概述，分主题展开，段尾列链接引用。
   - 存储：`months.monthly_summary`。

## LLM 在各阶段的作用
- **链接筛选**：决定哪些链接为 PRIMARY（抓正文）/ SUPPLEMENTARY（仅摘要），控制抓取与信噪。
- **事件摘要**：基于聚合的正文/摘要生成中文事件摘要，并排序/筛选事件。
- **月报撰写**: 生成结构化 Markdown 月报，引用来源链接。
- 不使用 LLM 的部分：搜索、去重、时间过滤、规则打标签、聚类、重要性初算。

## 主要提示词设计（摘录）
- 链接筛选（classify_links_importance）：挑选最值得抓正文的链接索引（偏好高质量媒体/宏观相关度），仅返回索引列表。
- 事件摘要（summarize_events_with_llm）：2-3 句中文，概括核心事实、传导渠道（就业/通胀/增长/金融条件），保持简洁。
- 事件筛选排序（llm_rank_and_filter）：按宏观重要性排序并筛选 5-12 条，偏好宏观冲击明确/影响显著/高可信媒体，输出索引列表。
- 月报生成（generate_monthly_report）：首段全貌，按主题分段（通胀/就业/增长/金融稳定/供应链/地缘等），段尾“来源：<链接…>”，Markdown 小标题/粗体，避免列表。

## 数据落盘
- `months`: 状态、事件数量、LLM/查询版本、事件 JSON、`monthly_summary`。
- `events`: 事件结构化字段 + `source_meta`（PRIMARY/SUPP 来源列表）。
- `raw_articles`: URL 唯一，保留 snippet/full_text/domain。

## 可调参数（config/服务层）
- 关键词模板（`UNIFIED_QUERIES`）
- 每轮 `max_results`、PRIMARY 上限
- 事件上限（默认 20），重要性阈值策略
- LLM 模型名（环境变量 `DEEPSEEK_MODEL` 或调用参数）

## 开发/调试提示
- 缺少 `DEEPSEEK_API_KEY` 会在 LLM 调用处报错（已自动加载 `.env`）。
- 重新抓取月度以刷新 raw_articles 正文与月报：`python manage_db.py refresh-month --month-key YYYY-MM --force`
