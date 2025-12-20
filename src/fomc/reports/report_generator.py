"""
Prompt builder + orchestrator for DeepSeek economic reports.

The generator separates prompt engineering (how we describe charts/data) from
the actual LLM call, keeping it easy to plug into future workflows or swap the
underlying provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from fomc.infra.llm import DeepSeekClient, DeepSeekConfig
from fomc.config.paths import PROMPT_RUNS_DIR, REPO_ROOT

PROMPT_DIR = REPO_ROOT / "content" / "prompts" / "reports"


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


def _load_prompt_template(filename: str) -> tuple[str, str, str, str, Path]:
    path = PROMPT_DIR / filename
    raw = path.read_text(encoding="utf-8")
    meta, template = _parse_front_matter(raw)
    prompt_id = meta.get("prompt_id") or path.stem
    prompt_version = meta.get("prompt_version") or "unknown"
    system_prompt = meta.get("system_prompt") or ""
    return template, prompt_id, prompt_version, system_prompt, path


def _render_prompt(template: str, context: dict) -> str:
    return template.format(**context).strip()


def _escape_format(text: str) -> str:
    return text.replace("{", "{{").replace("}", "}}")


@dataclass
class IndicatorSummary:
    """
    Structured representation of a single data point we want the LLM to cover.
    """

    name: str
    latest_value: str
    units: str
    mom_change: Optional[str] = None
    yoy_change: Optional[str] = None
    context: Optional[str] = None

    def as_prompt_line(self) -> str:
        deltas: List[str] = []
        if self.mom_change:
            deltas.append(f"环比: {self.mom_change}")
        if self.yoy_change:
            deltas.append(f"同比: {self.yoy_change}")

        delta_text = f" ({', '.join(deltas)})" if deltas else ""
        context_text = f" | 说明: {self.context}" if self.context else ""
        return f"- {self.name}: {self.latest_value}{self.units}{delta_text}{context_text}"


@dataclass
class ReportFocus:
    """
    Items that guide the narrative emphasis.
    """

    fomc_implications: Sequence[str] = field(default_factory=list)
    risks_to_watch: Sequence[str] = field(default_factory=list)
    market_reaction: Sequence[str] = field(default_factory=list)

    def format_section(self, title: str, items: Sequence[str]) -> str:
        if not items:
            return ""
        formatted_items = "\n".join(f"- {item}" for item in items)
        return f"{title}:\n{formatted_items}\n"

    def as_prompt_block(self) -> str:
        blocks = [
            self.format_section("FOMC考量", self.fomc_implications),
            self.format_section("需要警惕的风险", self.risks_to_watch),
            self.format_section("市场价格表现", self.market_reaction),
        ]
        return "\n".join(filter(None, blocks)).strip()


class EconomicReportGenerator:
    """
    Construct prompts for specific report types and call DeepSeek.
    """

    def __init__(self, client: Optional[DeepSeekClient] = None, config: Optional[DeepSeekConfig] = None):
        self.client = client or DeepSeekClient(config=config)
        self.multi_agent_default = os.getenv("FOMC_REPORT_MULTI_AGENT", "1").lower() not in ("0", "false", "no")

    def _record_prompt(
        self,
        *,
        report_type: str,
        report_month: str,
        system_prompt: str,
        user_prompt: str,
        prompt_id: str,
        prompt_version: str,
        agent_role: Optional[str] = None,
        prompt_source: Optional[str] = None,
        output_text: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> None:
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        safe_month = report_month.replace("/", "-").replace(" ", "_")
        run_dir = PROMPT_RUNS_DIR / report_type
        run_dir.mkdir(parents=True, exist_ok=True)
        run_id = run_id or stamp
        log_filename = f"{run_id}_{safe_month}.jsonl"
        log_path = run_dir / log_filename
        meta = {
            "report_type": report_type,
            "report_month": report_month,
            "prompt_id": prompt_id,
            "prompt_version": prompt_version,
            "agent_role": agent_role,
            "prompt_source": prompt_source,
            "model": self.client.config.model,
            "temperature": self.client.config.temperature,
            "max_tokens": self.client.config.max_tokens,
            "timestamp": stamp,
            "run_id": run_id,
            "log_file": log_filename,
            "prompt_chars": len(user_prompt),
            "output_chars": len(output_text) if output_text else 0,
            "prompt_template_path": str(PROMPT_DIR / f"{prompt_id}.md"),
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "output_text": output_text or "",
        }
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(meta, ensure_ascii=False))
            handle.write("\n")
    
    def _run_agent(
        self,
        *,
        report_type: str,
        report_month: str,
        agent_role: str,
        template_file: str,
        context: dict,
        fallback_system: str,
        run_id: Optional[str] = None,
    ) -> str:
        template, prompt_id, prompt_version, system_prompt, _ = _load_prompt_template(template_file)
        system_prompt = system_prompt or fallback_system
        user_prompt = _render_prompt(template, context)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        output = self.client.generate(messages)
        self._record_prompt(
            report_type=report_type,
            report_month=report_month,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            agent_role=agent_role,
            prompt_source="template",
            output_text=output,
            run_id=run_id,
        )
        return output

    def _build_nonfarm_context(
        self,
        report_month: str,
        headline_summary: str,
        labor_market_metrics: Sequence[IndicatorSummary],
        policy_focus: Optional[ReportFocus],
        chart_commentary: Optional[str],
        macro_events_context: Optional[str],
        tone: str,
    ) -> dict:
        metrics_block = "\n".join(metric.as_prompt_line() for metric in labor_market_metrics)
        focus_block = policy_focus.as_prompt_block() if policy_focus else ""
        chart_block = f"图表洞见:\n{chart_commentary}\n" if chart_commentary else ""
        macro_block = (
            f"当月宏观事件（来自新闻汇总，仅供参考）:\n{macro_events_context}\n"
            if macro_events_context
            else "当月宏观事件：未提供/未传入。\n"
        )
        return {
            "report_month": report_month,
            "headline_summary": headline_summary,
            "metrics_block": metrics_block,
            "chart_block": chart_block,
            "macro_block": macro_block,
            "focus_block": focus_block,
            "tone": tone,
        }

    def _build_cpi_context(
        self,
        report_month: str,
        headline_summary: str,
        inflation_metrics: Sequence[IndicatorSummary],
        contributions_text_yoy: str,
        contributions_text_mom: str,
        chart_commentary: Optional[str],
        macro_events_context: Optional[str],
        tone: str,
    ) -> dict:
        metrics_block = "\n".join(metric.as_prompt_line() for metric in inflation_metrics)
        macro_block = (
            f"当月宏观事件（来自新闻汇总，仅供参考）:\n{macro_events_context}\n"
            if macro_events_context
            else "当月宏观事件：未提供/未传入。\n"
        )
        return {
            "report_month": report_month,
            "headline_summary": headline_summary,
            "metrics_block": metrics_block,
            "contributions_text_yoy": contributions_text_yoy or "未提供同比拆分。",
            "contributions_text_mom": contributions_text_mom or "未提供环比拆分。",
            "chart_block": f"图表摘要:\n{chart_commentary}\n" if chart_commentary else "",
            "macro_block": macro_block,
            "tone": tone,
        }

    def generate_nonfarm_report(
        self,
        report_month: str,
        headline_summary: str,
        labor_market_metrics: Sequence[IndicatorSummary],
        policy_focus: Optional[ReportFocus] = None,
        chart_commentary: Optional[str] = None,
        macro_events_context: Optional[str] = None,
        tone: str = "专业严谨，突出数据结论后再解释逻辑，最后点评FOMC倾向。",
        multi_agent: Optional[bool] = None,
    ) -> str:
        """
        Generate a FOMC-style commentary around nonfarm payroll data.
        """

        prompt, prompt_id, prompt_version, system_prompt, context = self._build_nonfarm_prompt(
            report_month=report_month,
            headline_summary=headline_summary,
            labor_market_metrics=labor_market_metrics,
            policy_focus=policy_focus,
            chart_commentary=chart_commentary,
            macro_events_context=macro_events_context,
            tone=tone,
        )

        if not system_prompt:
            system_prompt = (
                "你是美联储研究部门的宏观经济学家，需要撰写结构化的美国劳动力市场点评。"
                "严禁编造或猜测未提供的数据；只能引用输入中明确给出的字段、指标或结论。"
                "若某数据缺失，请直接写明“数据未提供/未传入”，不要创造数值或行业分项。"
                "必须使用“当月宏观事件”段落做现实逻辑校验：至少提及2条事件并说明影响渠道；若未提供宏观事件则明确写出。"
            )

        use_multi_agent = self.multi_agent_default if multi_agent is None else multi_agent
        run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        draft = self.client.generate(messages)
        self._record_prompt(
            report_type="nfp",
            report_month=report_month,
            system_prompt=system_prompt,
            user_prompt=prompt,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            agent_role="draft",
            prompt_source="template",
            output_text=draft,
            run_id=run_id,
        )
        if not use_multi_agent:
            return draft

        inputs_block = _render_prompt(
            "报告月份: {report_month}\n核心结论: {headline_summary}\n劳动力市场关键数据:\n{metrics_block}\n{chart_block}{macro_block}{focus_block}".strip(),
            context,
        )
        shared_context = {
            "report_type": "非农",
            "inputs_block": _escape_format(inputs_block),
            "draft": _escape_format(draft),
        }
        consistency = self._run_agent(
            report_type="nfp",
            report_month=report_month,
            agent_role="consistency",
            template_file="report_consistency.md",
            context=shared_context,
            fallback_system="你是严谨的事实校对员。",
            run_id=run_id,
        )
        completeness = self._run_agent(
            report_type="nfp",
            report_month=report_month,
            agent_role="completeness",
            template_file="report_completeness.md",
            context=shared_context,
            fallback_system="你是严谨的结构检查员。",
            run_id=run_id,
        )
        logic = self._run_agent(
            report_type="nfp",
            report_month=report_month,
            agent_role="logic",
            template_file="report_logic.md",
            context=shared_context,
            fallback_system="你是宏观研究逻辑审阅员。",
            run_id=run_id,
        )
        editor_context = {
            **shared_context,
            "consistency_feedback": _escape_format(consistency),
            "completeness_feedback": _escape_format(completeness),
            "logic_feedback": _escape_format(logic),
        }
        return self._run_agent(
            report_type="nfp",
            report_month=report_month,
            agent_role="editor",
            template_file="report_editor.md",
            context=editor_context,
            fallback_system="你是资深宏观研报编辑。",
            run_id=run_id,
        )

    def generate_cpi_report(
        self,
        report_month: str,
        headline_summary: str,
        inflation_metrics: Sequence[IndicatorSummary],
        contributions_text_yoy: str = "",
        contributions_text_mom: str = "",
        chart_commentary: Optional[str] = None,
        macro_events_context: Optional[str] = None,
        tone: str = "强调数据定量支撑，客观描述驱动项与FOMC关切。",
        multi_agent: Optional[bool] = None,
    ) -> str:
        """Generate CPI-themed narrative."""

        prompt, prompt_id, prompt_version, system_prompt, context = self._build_cpi_prompt(
            report_month=report_month,
            headline_summary=headline_summary,
            inflation_metrics=inflation_metrics,
            contributions_text_yoy=contributions_text_yoy,
            contributions_text_mom=contributions_text_mom,
            chart_commentary=chart_commentary,
            macro_events_context=macro_events_context,
            tone=tone,
        )

        if not system_prompt:
            system_prompt = (
                "你是美联储研究部门的通胀分析师。只使用输入中提供的数据，不得编造或猜测缺失的数值、分项或权重。"
                "若某分项数据缺失，请明确指出“数据未提供”，不要自行补全。"
                "必须使用“当月宏观事件”段落做现实逻辑校验：至少提及2条事件并说明影响渠道；若未提供宏观事件则明确写出。"
            )

        use_multi_agent = self.multi_agent_default if multi_agent is None else multi_agent
        run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        draft = self.client.generate(messages)
        self._record_prompt(
            report_type="cpi",
            report_month=report_month,
            system_prompt=system_prompt,
            user_prompt=prompt,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            agent_role="draft",
            prompt_source="template",
            output_text=draft,
            run_id=run_id,
        )
        if not use_multi_agent:
            return draft

        inputs_block = _render_prompt(
            "报告月份: {report_month}\n核心结论: {headline_summary}\n关键通胀指标:\n{metrics_block}\n同比拉动拆分:\n{contributions_text_yoy}\n季调环比拆分:\n{contributions_text_mom}\n{chart_block}{macro_block}".strip(),
            context,
        )
        shared_context = {
            "report_type": "CPI",
            "inputs_block": _escape_format(inputs_block),
            "draft": _escape_format(draft),
        }
        consistency = self._run_agent(
            report_type="cpi",
            report_month=report_month,
            agent_role="consistency",
            template_file="report_consistency.md",
            context=shared_context,
            fallback_system="你是严谨的事实校对员。",
            run_id=run_id,
        )
        completeness = self._run_agent(
            report_type="cpi",
            report_month=report_month,
            agent_role="completeness",
            template_file="report_completeness.md",
            context=shared_context,
            fallback_system="你是严谨的结构检查员。",
            run_id=run_id,
        )
        logic = self._run_agent(
            report_type="cpi",
            report_month=report_month,
            agent_role="logic",
            template_file="report_logic.md",
            context=shared_context,
            fallback_system="你是宏观研究逻辑审阅员。",
            run_id=run_id,
        )
        editor_context = {
            **shared_context,
            "consistency_feedback": _escape_format(consistency),
            "completeness_feedback": _escape_format(completeness),
            "logic_feedback": _escape_format(logic),
        }
        return self._run_agent(
            report_type="cpi",
            report_month=report_month,
            agent_role="editor",
            template_file="report_editor.md",
            context=editor_context,
            fallback_system="你是资深宏观研报编辑。",
            run_id=run_id,
        )

    def _build_cpi_prompt(
        self,
        report_month: str,
        headline_summary: str,
        inflation_metrics: Sequence[IndicatorSummary],
        contributions_text_yoy: str,
        contributions_text_mom: str,
        chart_commentary: Optional[str],
        macro_events_context: Optional[str],
        tone: str,
    ) -> tuple[str, str, str, str, dict]:
        context = self._build_cpi_context(
            report_month=report_month,
            headline_summary=headline_summary,
            inflation_metrics=inflation_metrics,
            contributions_text_yoy=contributions_text_yoy,
            contributions_text_mom=contributions_text_mom,
            chart_commentary=chart_commentary,
            macro_events_context=macro_events_context,
            tone=tone,
        )
        template, prompt_id, prompt_version, system_prompt, _ = _load_prompt_template("cpi_report.md")
        return _render_prompt(template, context), prompt_id, prompt_version, system_prompt, context

    def _build_nonfarm_prompt(
        self,
        report_month: str,
        headline_summary: str,
        labor_market_metrics: Sequence[IndicatorSummary],
        policy_focus: Optional[ReportFocus],
        chart_commentary: Optional[str],
        macro_events_context: Optional[str],
        tone: str,
    ) -> tuple[str, str, str, str, dict]:
        context = self._build_nonfarm_context(
            report_month=report_month,
            headline_summary=headline_summary,
            labor_market_metrics=labor_market_metrics,
            policy_focus=policy_focus,
            chart_commentary=chart_commentary,
            macro_events_context=macro_events_context,
            tone=tone,
        )
        template, prompt_id, prompt_version, system_prompt, _ = _load_prompt_template("nfp_report.md")
        return _render_prompt(template, context), prompt_id, prompt_version, system_prompt, context
