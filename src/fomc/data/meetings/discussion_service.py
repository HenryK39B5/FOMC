from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple

from fomc.infra.llm import LLMClient


VoteDelta = Literal[-25, 0, 25, -50, 50]


def _extract_json_object(text: str) -> Dict[str, Any]:
    """
    Best-effort JSON object extractor for LLM outputs.

    We intentionally avoid being too smart: locate outermost {...} and parse.
    """
    if not text:
        raise ValueError("Empty LLM output")
    t = text.strip()
    start = t.find("{")
    end = t.rfind("}")
    if start < 0 or end < 0 or end <= start:
        raise ValueError("No JSON object found in output")
    blob = t[start : end + 1]
    return json.loads(blob)


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _ensure_list(x: Any) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def _to_int(x: Any) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None


def _format_fact_id(i: int) -> str:
    return f"F{i:02d}"


def _format_uncertainty_id(i: int) -> str:
    return f"U{i:02d}"


@dataclass(frozen=True)
class RoleProfile:
    role: str
    display_name: str
    bias: str
    style: str


DEFAULT_ROLES: list[RoleProfile] = [
    RoleProfile(
        role="centrist",
        display_name="Centrist",
        bias="偏中性：强调双重目标平衡，偏好渐进，重视政策滞后与风险对称性。",
        style="克制、审慎、条理清晰，常用“在不确定性下的风险管理”措辞。",
    ),
    RoleProfile(
        role="hawk",
        display_name="Hawk",
        bias="偏鹰：更强调通胀与预期锚定风险，容忍短期增长放缓，倾向更强硬的指引。",
        style="直接、有压迫感，但仍基于证据；会强调“通胀粘性/二次效应”。",
    ),
    RoleProfile(
        role="dove",
        display_name="Dove",
        bias="偏鸽：更强调就业与增长下行风险，关注金融条件收紧的滞后效应，倾向更耐心。",
        style="温和、同理、强调“避免过度紧缩/硬着陆”。",
    ),
]


def build_blackboard(
    *,
    meeting_id: str,
    source_materials: Dict[str, str],
    llm: Optional[LLMClient] = None,
    max_facts: int = 28,
    max_uncertainties: int = 8,
) -> Dict[str, Any]:
    """
    Build a shared blackboard used by all agents.

    source_materials keys: macro|nfp|cpi|taylor (markdown text)
    """
    llm = llm or LLMClient()
    macro = (source_materials.get("macro") or "").strip()
    nfp = (source_materials.get("nfp") or "").strip()
    cpi = (source_materials.get("cpi") or "").strip()
    taylor = (source_materials.get("taylor") or "").strip()

    prompt = (
        "你是“FOMC 历史会议模拟”的会议材料编辑。你将收到四份材料（宏观事件、劳动力、通胀、规则模型）。\n"
        "请严格基于材料内容抽取一个“共享黑板 blackboard”，供后续委员讨论引用。\n\n"
        "强约束（必须遵守）：\n"
        "1) 只能从材料里抽取或改写为更短的事实，不得引入材料之外的新事实/数值；\n"
        "2) facts 要短句化、可引用、可追溯（每条必须注明 source=macro|nfp|cpi|taylor）；\n"
        "3) uncertainties 是对材料中明确提到或暗示的关键不确定性/风险点，不得胡编；\n"
        "4) 输出必须是 JSON 对象（不要 Markdown，不要代码块）。\n\n"
        f"会议：{meeting_id}\n"
        f"facts 数量上限：{max_facts}\n"
        f"uncertainties 数量上限：{max_uncertainties}\n\n"
        "输出 JSON schema：\n"
        "{\n"
        '  "facts": [{"text": "...", "source": "macro|nfp|cpi|taylor"}],\n'
        '  "uncertainties": [{"text": "..."}],\n'
        '  "policy_menu": [{"key": "cut_25|hold|hike_25", "delta_bps": -25|0|25, "label": "..."}],\n'
        '  "draft_statement_slots": [{"key": "economic_activity|labor|inflation|financial_conditions|risks|policy_decision|forward_guidance|balance_sheet", "guidance": "..."}]\n'
        "}\n\n"
        "材料（可能较长，请抽取核心）：\n"
        f"[macro]\n{macro[:12000]}\n\n"
        f"[nfp]\n{nfp[:12000]}\n\n"
        f"[cpi]\n{cpi[:12000]}\n\n"
        f"[taylor]\n{taylor[:6000]}\n"
    )

    raw = llm.chat(
        [
            {"role": "system", "content": "Return ONLY valid JSON. Never fabricate facts or numbers."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=1800,
    )
    obj = _extract_json_object(raw)

    facts_in = _ensure_list(obj.get("facts"))
    uncertainties_in = _ensure_list(obj.get("uncertainties"))
    policy_menu_in = _ensure_list(obj.get("policy_menu"))
    slots_in = _ensure_list(obj.get("draft_statement_slots"))

    facts: list[dict] = []
    for idx, item in enumerate(facts_in[:max_facts], start=1):
        if not isinstance(item, dict):
            continue
        text = _normalize_ws(str(item.get("text") or ""))
        source = str(item.get("source") or "").strip().lower()
        if not text or source not in {"macro", "nfp", "cpi", "taylor"}:
            continue
        facts.append({"id": _format_fact_id(idx), "text": text, "source": source})

    uncertainties: list[dict] = []
    for idx, item in enumerate(uncertainties_in[:max_uncertainties], start=1):
        if not isinstance(item, dict):
            continue
        text = _normalize_ws(str(item.get("text") or ""))
        if not text:
            continue
        uncertainties.append({"id": _format_uncertainty_id(idx), "text": text})

    # Policy menu: default safe set if missing/invalid.
    policy_menu: list[dict] = []
    for it in policy_menu_in:
        if not isinstance(it, dict):
            continue
        key = str(it.get("key") or "").strip()
        delta = _to_int(it.get("delta_bps"))
        label = str(it.get("label") or "").strip() or key
        if key in {"cut_25", "hold", "hike_25"} and delta in {-25, 0, 25}:
            policy_menu.append({"key": key, "delta_bps": delta, "label": label})
    if not policy_menu:
        policy_menu = [
            {"key": "cut_25", "delta_bps": -25, "label": "降息 25bp"},
            {"key": "hold", "delta_bps": 0, "label": "维持不变"},
            {"key": "hike_25", "delta_bps": 25, "label": "加息 25bp"},
        ]

    slot_keys = {
        "economic_activity",
        "labor",
        "inflation",
        "financial_conditions",
        "risks",
        "policy_decision",
        "forward_guidance",
        "balance_sheet",
    }
    slots: list[dict] = []
    for it in slots_in:
        if not isinstance(it, dict):
            continue
        key = str(it.get("key") or "").strip()
        guidance = str(it.get("guidance") or "").strip()
        if key in slot_keys:
            slots.append({"key": key, "guidance": guidance})
    if not slots:
        slots = [{"key": k, "guidance": ""} for k in sorted(slot_keys)]

    return {
        "meeting_id": meeting_id,
        "facts": facts,
        "uncertainties": uncertainties,
        "policy_menu": policy_menu,
        "draft_statement_slots": slots,
        "rules": {
            "facts_must_be_cited": True,
            "allowed_vote_deltas_bps": [-25, 0, 25],
        },
    }


def infer_crisis_mode(blackboard: Dict[str, Any]) -> bool:
    """
    Conservative heuristic: keep crisis mode off unless the blackboard strongly signals it.

    We keep this simple for now; can be iterated later using more structured model outputs.
    """
    facts = blackboard.get("facts") or []
    for f in facts:
        if not isinstance(f, dict):
            continue
        t = str(f.get("text") or "")
        if any(k in t for k in ["紧急", "危机", "崩盘", "流动性枯竭"]):
            return True
    return False


def _validate_citations(
    *,
    cited_facts: Sequence[str],
    cited_uncertainties: Sequence[str],
    blackboard: Dict[str, Any],
) -> Tuple[bool, str]:
    facts_set = {f.get("id") for f in (blackboard.get("facts") or []) if isinstance(f, dict)}
    unc_set = {u.get("id") for u in (blackboard.get("uncertainties") or []) if isinstance(u, dict)}
    bad_f = [x for x in cited_facts if x not in facts_set]
    bad_u = [x for x in cited_uncertainties if x not in unc_set]
    if bad_f or bad_u:
        return False, f"Invalid citations: facts={bad_f} uncertainties={bad_u}"
    return True, ""


def _llm_json(
    llm: LLMClient,
    messages: Sequence[dict],
    *,
    temperature: float = 0.25,
    max_tokens: int = 1400,
    retry: int = 1,
) -> Dict[str, Any]:
    last_exc: Exception | None = None
    for _ in range(max(1, retry + 1)):
        try:
            raw = llm.chat(messages, temperature=temperature, max_tokens=max_tokens)
            return _extract_json_object(raw)
        except Exception as exc:
            last_exc = exc
            messages = list(messages) + [
                {
                    "role": "user",
                    "content": "上一次输出无法解析为 JSON。请严格输出一个 JSON 对象（不要 Markdown，不要代码块）。",
                }
            ]
    raise last_exc or RuntimeError("Failed to get JSON from LLM")


def generate_stance_card(
    *,
    meeting_id: str,
    role: RoleProfile,
    blackboard: Dict[str, Any],
    crisis_mode: bool,
    llm: Optional[LLMClient] = None,
) -> Dict[str, Any]:
    llm = llm or LLMClient()
    allowed = [-25, 0, 25] + ([-50, 50] if crisis_mode else [])
    prompt = (
        f"你是 FOMC 委员，角色设定：{role.display_name}。\n"
        f"偏好/立场：{role.bias}\n"
        f"表达风格：{role.style}\n\n"
        "请阅读 blackboard，并在私有通道写一张“立场卡 stance_card”。\n\n"
        "硬约束：\n"
        "1) 只能引用 blackboard.facts / blackboard.uncertainties（用编号），不得引入新事实/数值；\n"
        f"2) 投票只能在 allowed_vote_deltas_bps={allowed} 中选择；\n"
        "3) 输出必须是 JSON 对象（不要 Markdown，不要代码块）。\n\n"
        "输出 JSON schema：\n"
        "{\n"
        '  "role": "centrist|hawk|dove",\n'
        '  "preferred_delta_bps": -25|0|25,\n'
        '  "top_reasons": [{"fact_id": "F01", "reason": "..."}],\n'
        '  "key_risks": [{"uncertainty_id": "U01", "risk": "..."}],\n'
        '  "acceptable_compromises": ["..."],\n'
        '  "questions_to_ask": ["...","..."],\n'
        '  "one_sentence_position": "..." \n'
        "}\n\n"
        "blackboard:\n"
        + json.dumps(blackboard, ensure_ascii=False)
    )

    obj = _llm_json(
        llm,
        [
            {"role": "system", "content": "Return ONLY valid JSON. Never fabricate facts or numbers."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.25,
        max_tokens=1200,
        retry=1,
    )
    obj["role"] = role.role
    delta = _to_int(obj.get("preferred_delta_bps"))
    if delta not in allowed:
        obj["preferred_delta_bps"] = 0

    reasons = obj.get("top_reasons") or []
    cited_facts = [str(r.get("fact_id")) for r in reasons if isinstance(r, dict)]
    risks = obj.get("key_risks") or []
    cited_unc = [str(r.get("uncertainty_id")) for r in risks if isinstance(r, dict)]
    ok, err = _validate_citations(cited_facts=cited_facts, cited_uncertainties=cited_unc, blackboard=blackboard)
    if not ok:
        obj["citation_error"] = err
    return obj


def generate_public_speech(
    *,
    meeting_id: str,
    role: RoleProfile,
    blackboard: Dict[str, Any],
    stance_card: Dict[str, Any],
    phase_name: str,
    chair_question: Optional[str] = None,
    llm: Optional[LLMClient] = None,
) -> Dict[str, Any]:
    llm = llm or LLMClient()
    question_clause = ""
    if chair_question:
        question_clause = (
            "\n主持人给你的问题（你必须只回答这个问题）：\n"
            f"{chair_question}\n"
        )
    prompt = (
        f"你是 FOMC 委员，角色：{role.display_name}（{role.role}）。\n"
        f"当前阶段：{phase_name}\n"
        + question_clause
        + "\n硬约束：\n"
        "1) 公开发言必须只基于 blackboard.facts / blackboard.uncertainties（用编号引用），不得引入新事实；\n"
        "2) 发言要像逐字记录：第一人称、克制口语化、信息密度高；\n"
        "3) 输出必须是 JSON 对象（不要 Markdown，不要代码块）。\n\n"
        "输出 JSON schema：\n"
        "{\n"
        '  "role": "centrist|hawk|dove",\n'
        '  "speech_md": "Markdown 段落（不含标题）",\n'
        '  "cited_facts": ["F01","F02"],\n'
        '  "cited_uncertainties": ["U01"],\n'
        '  "ask_one_question": "（若是开场陈述则必须给出一个定向问题；若是回答主持人问题可留空）"\n'
        "}\n\n"
        "blackboard:\n"
        + json.dumps(blackboard, ensure_ascii=False)
        + "\n\nstance_card（供你保持一致立场）：\n"
        + json.dumps(stance_card, ensure_ascii=False)
    )

    obj = _llm_json(
        llm,
        [
            {"role": "system", "content": "Return ONLY valid JSON. Never fabricate facts or numbers."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.35,
        max_tokens=900,
        retry=1,
    )
    obj["role"] = role.role
    cited_facts = [str(x) for x in _ensure_list(obj.get("cited_facts"))]
    cited_unc = [str(x) for x in _ensure_list(obj.get("cited_uncertainties"))]
    ok, err = _validate_citations(cited_facts=cited_facts, cited_uncertainties=cited_unc, blackboard=blackboard)
    if not ok:
        obj["citation_error"] = err
    return obj


def chair_select_questions(
    *,
    meeting_id: str,
    blackboard: Dict[str, Any],
    stance_cards: Dict[str, Any],
    open_questions: List[str],
    llm: Optional[LLMClient] = None,
    max_questions: int = 6,
) -> Dict[str, Any]:
    llm = llm or LLMClient()
    prompt = (
        "你是 FOMC 主持人（Chair/Moderator）。\n"
        "请基于 stance_cards 与 open_questions，选择 3-6 个最关键分歧点进行定向质询。\n\n"
        "硬约束：\n"
        "1) 只能引用 blackboard 的事实编号来组织追问；不得引入新事实；\n"
        "2) 每个追问必须点名一个目标委员（centrist/hawk/dove），并且问题要具体可回答；\n"
        "3) 输出必须是 JSON 对象（不要 Markdown，不要代码块）。\n\n"
        f"max_questions={max_questions}\n\n"
        "输出 JSON schema：\n"
        "{\n"
        '  "chair_preface_md": "一小段控场文字（不含标题）",\n'
        '  "directed_questions": [{"to_role": "centrist|hawk|dove", "question": "..."}]\n'
        "}\n\n"
        "blackboard:\n"
        + json.dumps(blackboard, ensure_ascii=False)
        + "\n\nstance_cards:\n"
        + json.dumps(stance_cards, ensure_ascii=False)
        + "\n\nopen_questions:\n"
        + json.dumps(open_questions[:12], ensure_ascii=False)
    )
    obj = _llm_json(
        llm,
        [
            {"role": "system", "content": "Return ONLY valid JSON. Never fabricate facts or numbers."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.25,
        max_tokens=900,
        retry=1,
    )

    dq = []
    for it in _ensure_list(obj.get("directed_questions"))[:max_questions]:
        if not isinstance(it, dict):
            continue
        to_role = str(it.get("to_role") or "").strip().lower()
        q = _normalize_ws(str(it.get("question") or ""))
        if to_role in {"centrist", "hawk", "dove"} and q:
            dq.append({"to_role": to_role, "question": q})
    if len(dq) < 3:
        # fallback: round-robin
        roles = ["centrist", "hawk", "dove"]
        dq = []
        for idx, q in enumerate(open_questions[: max(3, min(max_questions, len(open_questions)))]):
            dq.append({"to_role": roles[idx % 3], "question": _normalize_ws(q)})

    return {
        "chair_preface_md": str(obj.get("chair_preface_md") or "").strip(),
        "directed_questions": dq,
    }


def chair_propose_packages(
    *,
    meeting_id: str,
    blackboard: Dict[str, Any],
    stance_cards: Dict[str, Any],
    llm: Optional[LLMClient] = None,
) -> Dict[str, Any]:
    llm = llm or LLMClient()
    prompt = (
        "你是 FOMC 主持人（Chair/Moderator）。\n"
        "请基于 blackboard 与各委员立场，提出 2-3 个“可投政策包”。\n"
        "每个政策包至少包括：利率决策（delta_bps），政策倾向（偏鹰/偏鸽/中性），以及一句简短指引措辞（中文）。\n\n"
        "硬约束：\n"
        "1) 利率决策 delta_bps 必须属于 blackboard.policy_menu 的 delta_bps；\n"
        "2) 不得引入 blackboard 之外的新事实/数值；\n"
        "3) 输出必须是 JSON 对象（不要 Markdown，不要代码块）。\n\n"
        "输出 JSON schema：\n"
        "{\n"
        '  "chair_transition_md": "一小段过渡控场文字（不含标题）",\n'
        '  "packages": [{"key": "A", "delta_bps": -25|0|25, "stance": "hawkish|neutral|dovish", "guidance": "..."}]\n'
        "}\n\n"
        "blackboard:\n"
        + json.dumps(blackboard, ensure_ascii=False)
        + "\n\nstance_cards:\n"
        + json.dumps(stance_cards, ensure_ascii=False)
    )
    obj = _llm_json(
        llm,
        [
            {"role": "system", "content": "Return ONLY valid JSON. Never fabricate facts or numbers."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=900,
        retry=1,
    )
    allowed = {int(it.get("delta_bps")) for it in (blackboard.get("policy_menu") or []) if isinstance(it, dict) and _to_int(it.get("delta_bps")) is not None}
    pkgs = []
    for it in _ensure_list(obj.get("packages"))[:3]:
        if not isinstance(it, dict):
            continue
        key = str(it.get("key") or "").strip() or "A"
        delta = _to_int(it.get("delta_bps"))
        stance = str(it.get("stance") or "").strip().lower()
        guidance = str(it.get("guidance") or "").strip()
        if delta not in allowed:
            continue
        if stance not in {"hawkish", "neutral", "dovish"}:
            stance = "neutral"
        pkgs.append({"key": key, "delta_bps": delta, "stance": stance, "guidance": guidance})
    if not pkgs:
        pkgs = [{"key": "A", "delta_bps": 0, "stance": "neutral", "guidance": "委员会将继续评估最新数据对前景的影响。"}]
    return {"chair_transition_md": str(obj.get("chair_transition_md") or "").strip(), "packages": pkgs}


def generate_package_preference(
    *,
    meeting_id: str,
    role: RoleProfile,
    blackboard: Dict[str, Any],
    stance_card: Dict[str, Any],
    packages: List[Dict[str, Any]],
    llm: Optional[LLMClient] = None,
) -> Dict[str, Any]:
    llm = llm or LLMClient()
    prompt = (
        f"你是 FOMC 委员 {role.display_name}（{role.role}）。\n"
        "主持人提出了若干政策包，请你对每个政策包给出：support/acceptable/oppose，并用一句话说明理由（必须引用 facts 编号）。\n\n"
        "硬约束：\n"
        "1) 只能引用 blackboard.facts（用编号），不得引入新事实；\n"
        "2) 输出必须是 JSON 对象（不要 Markdown，不要代码块）。\n\n"
        "输出 JSON schema：\n"
        "{\n"
        '  "role": "centrist|hawk|dove",\n'
        '  "package_views": [{"package_key": "A", "view": "support|acceptable|oppose", "because": "...", "cited_facts": ["F01","F02"]}]\n'
        "}\n\n"
        "packages:\n"
        + json.dumps(packages, ensure_ascii=False)
        + "\n\nblackboard:\n"
        + json.dumps(blackboard, ensure_ascii=False)
        + "\n\nstance_card:\n"
        + json.dumps(stance_card, ensure_ascii=False)
    )
    obj = _llm_json(
        llm,
        [
            {"role": "system", "content": "Return ONLY valid JSON. Never fabricate facts or numbers."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.25,
        max_tokens=900,
        retry=1,
    )
    obj["role"] = role.role
    views = []
    for it in _ensure_list(obj.get("package_views")):
        if not isinstance(it, dict):
            continue
        pk = str(it.get("package_key") or "").strip()
        view = str(it.get("view") or "").strip().lower()
        because = _normalize_ws(str(it.get("because") or ""))
        cited = [str(x) for x in _ensure_list(it.get("cited_facts"))]
        if view not in {"support", "acceptable", "oppose"}:
            continue
        ok, err = _validate_citations(cited_facts=cited, cited_uncertainties=[], blackboard=blackboard)
        if not ok:
            continue
        views.append({"package_key": pk, "view": view, "because": because, "cited_facts": cited})
    return {"role": role.role, "package_views": views}


def generate_vote(
    *,
    meeting_id: str,
    role: RoleProfile,
    blackboard: Dict[str, Any],
    stance_card: Dict[str, Any],
    packages: List[Dict[str, Any]],
    crisis_mode: bool,
    llm: Optional[LLMClient] = None,
) -> Dict[str, Any]:
    llm = llm or LLMClient()
    allowed = [-25, 0, 25] + ([-50, 50] if crisis_mode else [])
    prompt = (
        f"你是 FOMC 委员 {role.display_name}（{role.role}）。\n"
        "现在进入正式投票：请你选择本次利率调整 vote_delta_bps，并给出 50-120 字理由（必须引用 facts/uncertainties 编号）。\n\n"
        "硬约束：\n"
        "1) vote_delta_bps 必须属于 allowed_vote_deltas_bps；\n"
        "2) 只能引用 blackboard 的编号，不得引入新事实；\n"
        "3) 输出必须是 JSON 对象（不要 Markdown，不要代码块）。\n\n"
        f"allowed_vote_deltas_bps={allowed}\n\n"
        "输出 JSON schema：\n"
        "{\n"
        '  "role": "centrist|hawk|dove",\n'
        '  "vote_delta_bps": -25|0|25,\n'
        '  "reason": "...",\n'
        '  "cited_facts": ["F01","F02"],\n'
        '  "cited_uncertainties": ["U01"],\n'
        '  "dissent": false,\n'
        '  "dissent_sentence": ""\n'
        "}\n\n"
        "packages（供参考）：\n"
        + json.dumps(packages, ensure_ascii=False)
        + "\n\nblackboard:\n"
        + json.dumps(blackboard, ensure_ascii=False)
        + "\n\nstance_card:\n"
        + json.dumps(stance_card, ensure_ascii=False)
    )
    obj = _llm_json(
        llm,
        [
            {"role": "system", "content": "Return ONLY valid JSON. Never fabricate facts or numbers."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.25,
        max_tokens=700,
        retry=1,
    )
    obj["role"] = role.role
    delta = _to_int(obj.get("vote_delta_bps"))
    if delta not in allowed:
        obj["vote_delta_bps"] = 0
        obj["invalid_vote_reason"] = "vote_delta_bps out of allowed set"
    cited_facts = [str(x) for x in _ensure_list(obj.get("cited_facts"))]
    cited_unc = [str(x) for x in _ensure_list(obj.get("cited_uncertainties"))]
    ok, err = _validate_citations(cited_facts=cited_facts, cited_uncertainties=cited_unc, blackboard=blackboard)
    if not ok:
        obj["citation_error"] = err
    return obj


def secretary_round_summary(
    *,
    meeting_id: str,
    blackboard: Dict[str, Any],
    round_name: str,
    transcript_blocks: List[Dict[str, Any]],
    llm: Optional[LLMClient] = None,
) -> Dict[str, Any]:
    llm = llm or LLMClient()
    prompt = (
        "你是 FOMC 书记员（Secretary）。\n"
        "请对本轮公开讨论做结构化记录，便于后续拼装 Minutes 与 Statement。\n\n"
        "硬约束：\n"
        "1) 只能基于本轮 transcript 与 blackboard 编号做归纳；\n"
        "2) 输出必须是 JSON 对象（不要 Markdown，不要代码块）。\n\n"
        "输出 JSON schema：\n"
        "{\n"
        '  "round": "...",\n'
        '  "consensus": ["..."],\n'
        '  "disagreements": ["..."],\n'
        '  "open_questions_next": ["..."],\n'
        '  "statement_slot_notes": [{"slot_key": "inflation", "note": "..."}]\n'
        "}\n\n"
        f"round={round_name}\n\n"
        "blackboard:\n"
        + json.dumps(blackboard, ensure_ascii=False)
        + "\n\ntranscript_blocks:\n"
        + json.dumps(transcript_blocks, ensure_ascii=False)
    )
    obj = _llm_json(
        llm,
        [
            {"role": "system", "content": "Return ONLY valid JSON."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=900,
        retry=1,
    )
    obj["round"] = round_name
    obj["consensus"] = [str(x) for x in _ensure_list(obj.get("consensus"))][:10]
    obj["disagreements"] = [str(x) for x in _ensure_list(obj.get("disagreements"))][:10]
    obj["open_questions_next"] = [str(x) for x in _ensure_list(obj.get("open_questions_next"))][:10]
    notes = []
    for it in _ensure_list(obj.get("statement_slot_notes")):
        if not isinstance(it, dict):
            continue
        sk = str(it.get("slot_key") or "").strip()
        note = _normalize_ws(str(it.get("note") or ""))
        if sk and note:
            notes.append({"slot_key": sk, "note": note})
    obj["statement_slot_notes"] = notes[:16]
    return obj


def chair_write_statement_and_minutes(
    *,
    meeting_id: str,
    blackboard: Dict[str, Any],
    votes: List[Dict[str, Any]],
    round_summaries: List[Dict[str, Any]],
    llm: Optional[LLMClient] = None,
) -> Dict[str, str]:
    llm = llm or LLMClient()

    roles_in_vote = []
    for v in votes:
        if isinstance(v, dict) and v.get("role"):
            roles_in_vote.append(str(v.get("role")))
    roles_in_vote = sorted(set(roles_in_vote))

    def _vote_bucket(delta: Any) -> str:
        d = _to_int(delta)
        if d is None:
            return "unknown"
        if d < 0:
            return "cut"
        if d > 0:
            return "hike"
        return "hold"

    tally = {"cut": 0, "hold": 0, "hike": 0, "unknown": 0}
    for v in votes:
        if not isinstance(v, dict):
            continue
        tally[_vote_bucket(v.get("vote_delta_bps"))] += 1

    # Deterministic vote summary for the LLM to follow (prevents "9:1" hallucinations).
    # Format: "3:0" etc is computed from actual participants in this simulation.
    total = sum(tally.values())
    passed = max(tally["cut"], tally["hold"], tally["hike"])
    vote_summary = f"{passed}:{max(0, total - passed)}"

    prompt = (
        "你是 FOMC 主持人（Chair/Moderator），同时负责起草本次会议的 Statement 与 Minutes 摘要（中文）。\n\n"
        "硬约束：\n"
        "1) 不得引入 blackboard 之外的新事实/数值；\n"
        "2) 必须明确写出政策决定与投票结果，且投票人数必须与本次模拟参会委员数量一致；\n"
        "3) 严禁写出“9:1/10:0/11:0”等与本次模拟不一致的票数；\n"
        "4) 输出必须是 JSON 对象，包含 statement_md 与 minutes_summary_md 两个字段（不要 Markdown 代码块）。\n\n"
        "输出 JSON schema：\n"
        "{\n"
        '  "statement_md": "# ...\\n...\\n",\n'
        '  "minutes_summary_md": "# ...\\n...\\n"\n'
        "}\n\n"
        f"本次模拟参会委员 roles={roles_in_vote}（共 {len(roles_in_vote)} 人）\n"
        f"投票分布统计（必须严格使用，不得改写票数）：{tally}\n"
        f"投票结果简写（必须严格使用，不得改写票数）：{vote_summary}\n\n"
        "blackboard:\n"
        + json.dumps(blackboard, ensure_ascii=False)
        + "\n\nvotes:\n"
        + json.dumps(votes, ensure_ascii=False)
        + "\n\nround_summaries:\n"
        + json.dumps(round_summaries, ensure_ascii=False)
    )
    obj = _llm_json(
        llm,
        [
            {"role": "system", "content": "Return ONLY valid JSON. Never fabricate facts or numbers."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.25,
        max_tokens=2000,
        retry=1,
    )
    statement = str(obj.get("statement_md") or "").strip()
    minutes = str(obj.get("minutes_summary_md") or "").strip()
    if not statement.startswith("#"):
        statement = "# FOMC 声明（模拟）\n\n" + statement
    if not minutes.startswith("#"):
        minutes = "# 会议纪要摘要（模拟）\n\n" + minutes
    return {"statement_md": statement.strip() + "\n", "minutes_summary_md": minutes.strip() + "\n"}


def render_discussion_markdown(
    *,
    meeting_id: str,
    blackboard: Dict[str, Any],
    crisis_mode: bool,
    stance_cards: Dict[str, Any],
    opening_speeches: List[Dict[str, Any]],
    chair_q: Dict[str, Any],
    qa_speeches: List[Dict[str, Any]],
    packages: Dict[str, Any],
    package_views: List[Dict[str, Any]],
    votes: List[Dict[str, Any]],
) -> str:
    facts = blackboard.get("facts") or []
    uncs = blackboard.get("uncertainties") or []
    policy_menu = blackboard.get("policy_menu") or []

    def fmt_fact(f: dict) -> str:
        return f"- `{f.get('id')}` [{f.get('source')}] {f.get('text')}"

    def fmt_unc(u: dict) -> str:
        return f"- `{u.get('id')}` {u.get('text')}"

    def fmt_speech(block: dict) -> str:
        who = str(block.get("role") or "").strip()
        md = str(block.get("speech_md") or "").strip()
        cited_f = ", ".join([str(x) for x in _ensure_list(block.get("cited_facts"))])
        cited_u = ", ".join([str(x) for x in _ensure_list(block.get("cited_uncertainties"))])
        cite_line = []
        if cited_f:
            cite_line.append(f"facts: {cited_f}")
        if cited_u:
            cite_line.append(f"uncertainties: {cited_u}")
        cite = f"\n\n> 引用：{' · '.join(cite_line)}" if cite_line else ""
        return f"**{who.upper()}**：\n\n{md}{cite}\n"

    lines: list[str] = []
    lines.append("# 委员讨论逐字记录（模拟）\n")
    lines.append(f"Meeting: {meeting_id}\n")
    lines.append(f"- crisis_mode: `{str(bool(crisis_mode)).lower()}`\n")
    lines.append("")
    lines.append("## 讨论底稿（可引用要点 / facts）\n")
    for f in facts:
        if isinstance(f, dict):
            lines.append(fmt_fact(f))
    lines.append("")
    lines.append("## 关键不确定性（uncertainties）\n")
    for u in uncs:
        if isinstance(u, dict):
            lines.append(fmt_unc(u))
    lines.append("")
    lines.append("## 可投政策选项（policy_menu）\n")
    for it in policy_menu:
        if isinstance(it, dict):
            lines.append(f"- `{it.get('key')}`: {it.get('label')}（{it.get('delta_bps')}bp）")
    lines.append("")

    lines.append("## Phase 1：立场卡（私有，不进入逐字稿）\n")
    for k, v in stance_cards.items():
        if isinstance(v, dict):
            lines.append(f"- {k}: preferred_delta_bps={v.get('preferred_delta_bps')}")
    lines.append("")

    lines.append("## Phase 2：开场陈述（公开）\n")
    for b in opening_speeches:
        lines.append(fmt_speech(b))
        q = str(b.get("ask_one_question") or "").strip()
        if q:
            lines.append(f"> 定向问题：{q}\n")
    lines.append("")

    lines.append("## Phase 3：定向质询（公开）\n")
    preface = str(chair_q.get("chair_preface_md") or "").strip()
    if preface:
        lines.append(f"**CHAIR**：\n\n{preface}\n")
    dq = [it for it in (chair_q.get("directed_questions") or []) if isinstance(it, dict)]
    # Pair questions with answers in display order for readability.
    for idx, it in enumerate(dq):
        lines.append(f"**CHAIR（点名）**：请 `{it.get('to_role')}` 回答：{it.get('question')}\n")
        if idx < len(qa_speeches):
            lines.append(fmt_speech(qa_speeches[idx]))
        else:
            lines.append("> （暂无回答记录）\n")
    lines.append("")

    lines.append("## Phase 4：政策包讨论与投票\n")
    trans = str(packages.get("chair_transition_md") or "").strip()
    if trans:
        lines.append(f"**CHAIR**：\n\n{trans}\n")
    lines.append("### 主持人提出的政策方案\n")
    for p in packages.get("packages") or []:
        if isinstance(p, dict):
            lines.append(f"- 包{p.get('key')}: delta_bps={p.get('delta_bps')} · {p.get('stance')} · {p.get('guidance')}")
    lines.append("")
    lines.append("### 委员对政策方案的态度\n")
    for v in package_views:
        if not isinstance(v, dict):
            continue
        role = v.get("role")
        views = v.get("package_views") or []
        if not views:
            continue
        lines.append(f"**{str(role).upper()}**：")
        for it in views:
            if not isinstance(it, dict):
                continue
            lines.append(f"- {it.get('package_key')}: {it.get('view')} · {it.get('because')}（引用 {', '.join(it.get('cited_facts') or [])}）")
        lines.append("")
    lines.append("### 正式投票\n")
    for v in votes:
        if not isinstance(v, dict):
            continue
        role = str(v.get("role") or "").upper()
        delta = v.get("vote_delta_bps")
        reason = str(v.get("reason") or "").strip()
        cited_f = ", ".join([str(x) for x in _ensure_list(v.get("cited_facts"))])
        cited_u = ", ".join([str(x) for x in _ensure_list(v.get("cited_uncertainties"))])
        lines.append(f"- **{role}**：{delta}bp · {reason}（facts: {cited_f} | uncertainties: {cited_u}）")
        if v.get("dissent") and str(v.get("dissent_sentence") or "").strip():
            lines.append(f"  - 异议：{str(v.get('dissent_sentence')).strip()}")
    lines.append("")
    return "\n".join(lines).strip() + "\n"
