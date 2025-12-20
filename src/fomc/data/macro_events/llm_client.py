"""Thin client wrappers for macro-events LLM calls (shared DeepSeek client)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fomc.infra.llm import LLMClient
from fomc.config.paths import PROMPT_RUNS_DIR, REPO_ROOT

PROMPT_DIR = REPO_ROOT / "content" / "prompts" / "reports"
MACRO_MONTHLY_PROMPT_FILE = "macro_monthly_report.md"


def _parse_front_matter(raw: str) -> Tuple[dict, str]:
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


def _record_prompt_run(
    *,
    report_month: str,
    system_prompt: str,
    user_prompt: str,
    prompt_id: str,
    prompt_version: str,
    prompt_source: str,
    output_text: str,
    run_id: Optional[str] = None,
) -> None:
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    safe_month = report_month.replace("/", "-").replace(" ", "_") if report_month else "unknown"
    run_dir = PROMPT_RUNS_DIR / "macro"
    run_dir.mkdir(parents=True, exist_ok=True)
    run_id = run_id or stamp
    log_filename = f"{run_id}_{safe_month}.jsonl"
    log_path = run_dir / log_filename
    meta = {
        "report_type": "macro",
        "report_month": report_month,
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
        "prompt_source": prompt_source,
        "model": LLMClient().config.model,
        "temperature": 0.3,
        "max_tokens": 900,
        "timestamp": stamp,
        "run_id": run_id,
        "log_file": log_filename,
        "prompt_chars": len(user_prompt),
        "output_chars": len(output_text),
        "prompt_template_path": str(PROMPT_DIR / f"{prompt_id}.md"),
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "output_text": output_text,
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(meta, ensure_ascii=False))
        handle.write("\n")


def call_llm(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 512,
) -> str:
    """
    Call the shared LLM client for chat completions.
    """
    client = LLMClient()
    return client.chat(messages, model=model, temperature=temperature, max_tokens=max_tokens)


def summarize_events_with_llm(events: List[Dict], report_type: str, model: Optional[str] = None) -> List[Dict]:
    """
    Iterate through events and enrich summary_zh using LLM output.
    """
    enhanced: List[Dict] = []
    for event in events:
        prompt = (
            "你是一名宏观经济分析师，请用简洁中文总结该事件，2-3 句："
            "1) 交代事件核心事实与冲击方向；"
            "2) 指出主要传导渠道（就业/通胀/增长/金融条件）；"
            "3) 避免堆砌来源，保持简练。"
            "\n\n事件信息："
            f"{event}"
        )
        summary = call_llm(
            [
                {"role": "system", "content": "你是严谨的宏观研究助理。"},
                {"role": "user", "content": prompt},
            ],
            model=model,
            max_tokens=256,
        )
        event = dict(event)
        event["summary_zh"] = summary.strip()
        enhanced.append(event)
    return enhanced


def llm_rank_and_filter(events: List[Dict], model: Optional[str] = None) -> List[Dict]:
    """
    Ask LLM to decide which events to keep based on importance/context.
    Returns reordered/filtered list. Falls back to original on failure.
    """
    if not events:
        return events
    prompt = (
        "你是一名宏观研究助理。给定当月事件列表（JSON），按“宏观重要性”排序并筛选 5-12 条，"
        "优先：宏观冲击明确、对就业/通胀/增长/金融条件影响显著、高可信媒体。"
        "仅输出索引数字（0-based），用逗号分隔，如 0,1,2,5，不要解释。"
        "\n\n事件列表：\n"
    )
    body = prompt + str(events)
    resp = call_llm(
        [
            {"role": "system", "content": "你是严谨的宏观事件筛选器，只返回索引列表。"},
            {"role": "user", "content": body},
        ],
        model=model,
        max_tokens=128,
    )
    idx_tokens = [t.strip() for t in resp.replace("\n", " ").split(",") if t.strip().isdigit()]
    idxs = [int(t) for t in idx_tokens if t.isdigit()]
    seen = set()
    picked = []
    for i in idxs:
        if 0 <= i < len(events) and i not in seen:
            picked.append(events[i])
            seen.add(i)
    if 5 <= len(picked) <= 12:
        return picked
    # If LLM returns fewer/more than expected, fall back to original ordering.
    return events


def extract_event_keywords(
    events: List[Dict],
    report_type: str,
    model: Optional[str] = None,
    max_keywords: int = 12,
) -> List[str]:
    """
    Extract event-level search keywords for stage-2 retrieval.
    """
    if not events:
        return []
    prompt = (
        "你是一名宏观研究助理。给定当月事件列表（JSON），提炼可用于新闻检索的关键词/短语，"
        "每条 2-6 个词，尽量具体（含实体/指标/事件名）。请只输出英文关键词/短语。"
        "输出 JSON 数组，不要解释。"
        f"最多 {max_keywords} 条。\n\n事件列表：\n"
    )
    body = prompt + str(events)
    resp = call_llm(
        [
            {"role": "system", "content": "你只返回 JSON 数组。"},
            {"role": "user", "content": body},
        ],
        model=model,
        max_tokens=256,
    )
    keywords: List[str] = []
    try:
        import json

        data = json.loads(resp.strip())
        if isinstance(data, list):
            keywords = [str(item).strip() for item in data if str(item).strip()]
    except Exception:
        raw = resp.replace("\n", ",")
        parts = [p.strip(" -\t\r\"'") for p in raw.split(",")]
        keywords = [p for p in parts if p]
    return keywords[:max_keywords]


def generate_monthly_report(
    events: List[Dict],
    model: Optional[str] = None,
    report_month: Optional[str] = None,
) -> Optional[str]:
    if not events:
        return None
    system_prompt = "你是严谨的宏观事件分析师。"
    prompt = (
        "你是一名宏观经济研究员，请撰写“宏观事件月报”。要求：\n"
        "1) 首段 2-3 句概述本月宏观冲击全貌。\n"
        "2) 按主题/冲击渠道分段（通胀/就业/增长/金融稳定/供应链/地缘等），每段 3-4 句，展开核心事实与传导渠道。\n"
        "3) 每段末尾附“来源”行，列出该段相关报道链接（用空格分隔）。\n"
        "4) 使用 Markdown 渲染：小标题（##）、段落、粗体，避免列表。\n"
        "\n事件数据（JSON，含 source_urls/source_domains）：\n"
        f"{events}"
    )
    prompt_id = "macro_monthly_report"
    prompt_version = "fallback"
    prompt_source = "fallback"
    try:
        prompt_id, prompt_version, system_prompt, template = _load_prompt_template(MACRO_MONTHLY_PROMPT_FILE)
        events_json = json.dumps(events, ensure_ascii=False)
        prompt = template.format(events_json=events_json)
        prompt_source = "template"
    except Exception:
        pass
    output = call_llm(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        model=model,
        max_tokens=900,
    )
    try:
        _record_prompt_run(
            report_month=report_month or "",
            system_prompt=system_prompt,
            user_prompt=prompt,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            prompt_source=prompt_source,
            output_text=output,
            run_id=datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"),
        )
    except Exception:
        pass
    return output


def classify_links_importance(news_items: List[Dict], max_primary: int = 12, model: Optional[str] = None) -> List[int]:
    """
    Return indices (0-based) of links to mark as primary/important.
    """
    if not news_items:
        return []
    content = "\n".join(
        f"{idx}: {item.get('source') or ''} | {item.get('title') or ''}"
        for idx, item in enumerate(news_items[:60])
    )
    prompt = (
        "以下是本月新闻标题与来源，请挑选最值得保留并抓正文的链接索引（0-based），"
        f"最多 {max_primary} 条，偏好高质量媒体与宏观相关度高的标题。仅输出索引，用逗号分隔。"
        "\n\n"
        f"{content}"
    )
    resp = call_llm(
        [
            {"role": "system", "content": "你只返回索引数字列表，不要解释。"},
            {"role": "user", "content": prompt},
        ],
        model=model,
        max_tokens=64,
    )
    idx_tokens = [t.strip() for t in resp.replace("\n", " ").split(",") if t.strip().isdigit()]
    idxs = []
    for t in idx_tokens:
        try:
            i = int(t)
        except Exception:
            continue
        if 0 <= i < len(news_items) and len(idxs) < max_primary:
            idxs.append(i)
    return idxs
