"""
Prompt builder + orchestrator for DeepSeek economic reports.

The generator separates prompt engineering (how we describe charts/data) from
the actual LLM call, keeping it easy to plug into future workflows or swap the
underlying provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from .deepseek_client import DeepSeekClient, DeepSeekConfig


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

    def generate_nonfarm_report(
        self,
        report_month: str,
        headline_summary: str,
        labor_market_metrics: Sequence[IndicatorSummary],
        policy_focus: Optional[ReportFocus] = None,
        chart_commentary: Optional[str] = None,
        tone: str = "专业严谨，突出数据结论后再解释逻辑，最后点评FOMC倾向。",
    ) -> str:
        """
        Generate a FOMC-style commentary around nonfarm payroll data.
        """

        prompt = self._build_nonfarm_prompt(
            report_month=report_month,
            headline_summary=headline_summary,
            labor_market_metrics=labor_market_metrics,
            policy_focus=policy_focus,
            chart_commentary=chart_commentary,
            tone=tone,
        )

        messages = [
            {
                "role": "system",
                "content": "你是美联储研究部门的宏观经济学家，需要撰写结构化的美国劳动力市场点评。",
            },
            {"role": "user", "content": prompt},
        ]

        return self.client.generate(messages)

    def _build_nonfarm_prompt(
        self,
        report_month: str,
        headline_summary: str,
        labor_market_metrics: Sequence[IndicatorSummary],
        policy_focus: Optional[ReportFocus],
        chart_commentary: Optional[str],
        tone: str,
    ) -> str:
        metrics_block = "\n".join(metric.as_prompt_line() for metric in labor_market_metrics)
        focus_block = policy_focus.as_prompt_block() if policy_focus else ""
        chart_block = f"图表洞见:\n{chart_commentary}\n" if chart_commentary else ""

        sections = [
            f"报告月份: {report_month}",
            f"核心结论: {headline_summary}",
            "劳动力市场关键数据:",
            metrics_block,
            chart_block,
            focus_block,
            f"写作语气: {tone}",
            "输出要求: 先给数据结论，再解释驱动因素，最后分析对下次FOMC会议的影响。结构采用段落+小标题。",
        ]

        return "\n".join(section for section in sections if section).strip()
