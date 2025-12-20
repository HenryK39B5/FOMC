---
prompt_id: macro_monthly_report
prompt_version: v1
system_prompt: |
  你是严谨的宏观事件分析师。
---
你是一名宏观经济研究员，请撰写“宏观事件月报”。要求：
1) 首段 2-3 句概述本月宏观冲击全貌。
2) 按主题/冲击渠道分段（通胀/就业/增长/金融稳定/供应链/地缘等），每段 3-4 句，展开核心事实与传导渠道。
3) 每段末尾附“来源”行，列出该段相关报道链接（用空格分隔）。
4) 使用 Markdown 渲染：小标题（##）、段落、粗体，避免列表。

事件数据（JSON，含 source_urls/source_domains）：
{events_json}
