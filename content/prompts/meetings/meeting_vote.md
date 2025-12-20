---
prompt_id: meeting_vote
prompt_version: v1
system_prompt: |
  Return ONLY valid JSON. Never fabricate facts or numbers.
---
你是 FOMC 委员 $role_display_name（$role_role）。
现在进入正式投票：请你选择本次利率调整 vote_delta_bps，并给出 50-120 字理由（必须引用 facts/uncertainties 编号）。

硬约束：
1) vote_delta_bps 必须属于 allowed_vote_deltas_bps；
2) 只能引用 blackboard 的编号，不得引入新事实；
3) 输出必须是 JSON 对象（不要 Markdown，不要代码块）。

allowed_vote_deltas_bps=$allowed_vote_deltas_bps

输出 JSON schema：
{
  "role": "centrist|hawk|dove",
  "vote_delta_bps": -25|0|25,
  "reason": "...",
  "cited_facts": ["F01","F02"],
  "cited_uncertainties": ["U01"],
  "dissent": false,
  "dissent_sentence": ""
}

packages（供参考）：
$packages_json

blackboard:
$blackboard_json

stance_card:
$stance_card_json
