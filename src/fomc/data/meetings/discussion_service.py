from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import re
from string import Template
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple

from fomc.config.paths import PROMPT_RUNS_DIR, REPO_ROOT
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


PROMPT_DIR = REPO_ROOT / "content" / "prompts" / "meetings"


def _parse_front_matter(raw: str) -> tuple[dict, str]:
    if not raw.startswith("---\n"):
        return {}, raw
    marker = "\n---\n"
    end = raw.find(marker, 4)
    if end == -1:
        return {}, raw
    header = raw[4:end].splitlines()
    body = raw[end + len(marker) :]
    meta: dict = {}
    i = 0
    while i < len(header):
        line = header[i].rstrip()
        if not line or line.lstrip().startswith("#"):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "|":
            i += 1
            block_lines = []
            while i < len(header):
                raw_line = header[i]
                if raw_line.startswith("  "):
                    block_lines.append(raw_line[2:])
                    i += 1
                    continue
                break
            meta[key] = "\n".join(block_lines).strip()
            continue
        meta[key] = value
        i += 1
    return meta, body


def _load_prompt_template(filename: str) -> tuple[str, str, str, str]:
    path = PROMPT_DIR / filename
    raw = path.read_text(encoding="utf-8")
    meta, template = _parse_front_matter(raw)
    prompt_id = meta.get("prompt_id") or path.stem
    prompt_version = meta.get("prompt_version") or "unknown"
    system_prompt = meta.get("system_prompt") or ""
    return prompt_id, prompt_version, system_prompt, template.strip()


def _render_template(template: str, context: dict) -> str:
    return Template(template).safe_substitute(**context).strip()


def _log_prompt_run(
    *,
    meeting_id: str,
    prompt_id: str,
    prompt_version: str,
    agent_role: str,
    prompt_source: str,
    system_prompt: str,
    user_prompt: str,
    output_text: str,
    model: str,
    temperature: float,
    max_tokens: int,
) -> None:
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    safe_meeting_id = meeting_id.replace("/", "-").replace(" ", "_").replace(":", "-")
    run_dir = PROMPT_RUNS_DIR / "meetings"
    run_dir.mkdir(parents=True, exist_ok=True)
    log_filename = f"{safe_meeting_id}.jsonl"
    log_path = run_dir / log_filename
    meta = {
        "report_type": "meeting",
        "meeting_id": meeting_id,
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
        "agent_role": agent_role,
        "prompt_source": prompt_source,
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timestamp": stamp,
        "log_file": log_filename,
        "prompt_chars": len(user_prompt),
        "output_chars": len(output_text),
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "output_text": output_text,
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(meta, ensure_ascii=False))
        handle.write("\n")


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

    prompt_id, prompt_version, system_prompt, template = _load_prompt_template("meeting_blackboard.md")
    prompt = _render_template(
        template,
        {
            "meeting_id": meeting_id,
            "max_facts": max_facts,
            "max_uncertainties": max_uncertainties,
            "macro": macro[:12000],
            "nfp": nfp[:12000],
            "cpi": cpi[:12000],
            "taylor": taylor[:6000],
        },
    )

    raw = llm.chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=1800,
    )
    obj = _extract_json_object(raw)
    try:
        _log_prompt_run(
            meeting_id=meeting_id,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            agent_role="blackboard",
            prompt_source="template",
            system_prompt=system_prompt,
            user_prompt=prompt,
            output_text=raw,
            model=llm.config.model,
            temperature=0.2,
            max_tokens=1800,
        )
    except Exception:
        pass

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
    prompt_id, prompt_version, system_prompt, template = _load_prompt_template("meeting_stance_card.md")
    prompt = _render_template(
        template,
        {
            "role_display_name": role.display_name,
            "role_bias": role.bias,
            "role_style": role.style,
            "allowed_vote_deltas_bps": json.dumps(allowed, ensure_ascii=False),
            "blackboard_json": json.dumps(blackboard, ensure_ascii=False),
        },
    )

    obj = _llm_json(
        llm,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0.25,
        max_tokens=1200,
        retry=1,
    )
    try:
        _log_prompt_run(
            meeting_id=meeting_id,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            agent_role="stance_card",
            prompt_source="template",
            system_prompt=system_prompt,
            user_prompt=prompt,
            output_text=json.dumps(obj, ensure_ascii=False),
            model=llm.config.model,
            temperature=0.25,
            max_tokens=1200,
        )
    except Exception:
        pass
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
    prompt_id, prompt_version, system_prompt, template = _load_prompt_template("meeting_public_speech.md")
    prompt = _render_template(
        template,
        {
            "role_display_name": role.display_name,
            "role_role": role.role,
            "phase_name": phase_name,
            "question_clause": question_clause,
            "blackboard_json": json.dumps(blackboard, ensure_ascii=False),
            "stance_card_json": json.dumps(stance_card, ensure_ascii=False),
        },
    )

    obj = _llm_json(
        llm,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0.35,
        max_tokens=900,
        retry=1,
    )
    try:
        _log_prompt_run(
            meeting_id=meeting_id,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            agent_role="public_speech",
            prompt_source="template",
            system_prompt=system_prompt,
            user_prompt=prompt,
            output_text=json.dumps(obj, ensure_ascii=False),
            model=llm.config.model,
            temperature=0.35,
            max_tokens=900,
        )
    except Exception:
        pass
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
    prompt_id, prompt_version, system_prompt, template = _load_prompt_template("meeting_chair_questions.md")
    prompt = _render_template(
        template,
        {
            "max_questions": max_questions,
            "blackboard_json": json.dumps(blackboard, ensure_ascii=False),
            "stance_cards_json": json.dumps(stance_cards, ensure_ascii=False),
            "open_questions_json": json.dumps(open_questions[:12], ensure_ascii=False),
        },
    )
    obj = _llm_json(
        llm,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0.25,
        max_tokens=900,
        retry=1,
    )
    try:
        _log_prompt_run(
            meeting_id=meeting_id,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            agent_role="chair_questions",
            prompt_source="template",
            system_prompt=system_prompt,
            user_prompt=prompt,
            output_text=json.dumps(obj, ensure_ascii=False),
            model=llm.config.model,
            temperature=0.25,
            max_tokens=900,
        )
    except Exception:
        pass

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
    prompt_id, prompt_version, system_prompt, template = _load_prompt_template("meeting_chair_packages.md")
    prompt = _render_template(
        template,
        {
            "blackboard_json": json.dumps(blackboard, ensure_ascii=False),
            "stance_cards_json": json.dumps(stance_cards, ensure_ascii=False),
        },
    )
    obj = _llm_json(
        llm,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=900,
        retry=1,
    )
    try:
        _log_prompt_run(
            meeting_id=meeting_id,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            agent_role="chair_packages",
            prompt_source="template",
            system_prompt=system_prompt,
            user_prompt=prompt,
            output_text=json.dumps(obj, ensure_ascii=False),
            model=llm.config.model,
            temperature=0.2,
            max_tokens=900,
        )
    except Exception:
        pass
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
    prompt_id, prompt_version, system_prompt, template = _load_prompt_template("meeting_package_preference.md")
    prompt = _render_template(
        template,
        {
            "role_display_name": role.display_name,
            "role_role": role.role,
            "packages_json": json.dumps(packages, ensure_ascii=False),
            "blackboard_json": json.dumps(blackboard, ensure_ascii=False),
            "stance_card_json": json.dumps(stance_card, ensure_ascii=False),
        },
    )
    obj = _llm_json(
        llm,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0.25,
        max_tokens=900,
        retry=1,
    )
    try:
        _log_prompt_run(
            meeting_id=meeting_id,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            agent_role="package_preference",
            prompt_source="template",
            system_prompt=system_prompt,
            user_prompt=prompt,
            output_text=json.dumps(obj, ensure_ascii=False),
            model=llm.config.model,
            temperature=0.25,
            max_tokens=900,
        )
    except Exception:
        pass
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
    prompt_id, prompt_version, system_prompt, template = _load_prompt_template("meeting_vote.md")
    prompt = _render_template(
        template,
        {
            "role_display_name": role.display_name,
            "role_role": role.role,
            "allowed_vote_deltas_bps": json.dumps(allowed, ensure_ascii=False),
            "packages_json": json.dumps(packages, ensure_ascii=False),
            "blackboard_json": json.dumps(blackboard, ensure_ascii=False),
            "stance_card_json": json.dumps(stance_card, ensure_ascii=False),
        },
    )
    obj = _llm_json(
        llm,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0.25,
        max_tokens=700,
        retry=1,
    )
    try:
        _log_prompt_run(
            meeting_id=meeting_id,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            agent_role="vote",
            prompt_source="template",
            system_prompt=system_prompt,
            user_prompt=prompt,
            output_text=json.dumps(obj, ensure_ascii=False),
            model=llm.config.model,
            temperature=0.25,
            max_tokens=700,
        )
    except Exception:
        pass
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
    prompt_id, prompt_version, system_prompt, template = _load_prompt_template("meeting_secretary_round.md")
    prompt = _render_template(
        template,
        {
            "round_name": round_name,
            "blackboard_json": json.dumps(blackboard, ensure_ascii=False),
            "transcript_blocks_json": json.dumps(transcript_blocks, ensure_ascii=False),
        },
    )
    obj = _llm_json(
        llm,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=900,
        retry=1,
    )
    try:
        _log_prompt_run(
            meeting_id=meeting_id,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            agent_role="secretary_round",
            prompt_source="template",
            system_prompt=system_prompt,
            user_prompt=prompt,
            output_text=json.dumps(obj, ensure_ascii=False),
            model=llm.config.model,
            temperature=0.2,
            max_tokens=900,
        )
    except Exception:
        pass
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

    prompt_id, prompt_version, system_prompt, template = _load_prompt_template("meeting_statement_minutes.md")
    prompt = _render_template(
        template,
        {
            "roles_in_vote": json.dumps(roles_in_vote, ensure_ascii=False),
            "roles_count": len(roles_in_vote),
            "tally_json": json.dumps(tally, ensure_ascii=False),
            "vote_summary": vote_summary,
            "blackboard_json": json.dumps(blackboard, ensure_ascii=False),
            "votes_json": json.dumps(votes, ensure_ascii=False),
            "round_summaries_json": json.dumps(round_summaries, ensure_ascii=False),
        },
    )
    obj = _llm_json(
        llm,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0.25,
        max_tokens=2000,
        retry=1,
    )
    try:
        _log_prompt_run(
            meeting_id=meeting_id,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            agent_role="chair_statement_minutes",
            prompt_source="template",
            system_prompt=system_prompt,
            user_prompt=prompt,
            output_text=json.dumps(obj, ensure_ascii=False),
            model=llm.config.model,
            temperature=0.25,
            max_tokens=2000,
        )
    except Exception:
        pass
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
