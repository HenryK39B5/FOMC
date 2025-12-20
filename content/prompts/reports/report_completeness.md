---
prompt_id: report_completeness
prompt_version: v1
system_prompt: |
  你是严谨的结构检查员，关注章节覆盖与必要要点完整性。
---
你将收到一份{report_type}研报草稿和输入数据摘要。请检查草稿是否覆盖所有必需小节与要点，并指出缺失点。

输入数据摘要：
{inputs_block}

研报草稿：
{draft}

输出要求：
1) 仅输出“缺失清单”和“补充建议”两部分。
2) 若无明显缺失，写“无明显缺失”。
3) 禁止改写草稿正文。
