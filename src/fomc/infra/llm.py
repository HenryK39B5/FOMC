"""
Shared LLM client (DeepSeek-compatible) for the whole project.

All components should import and use this module instead of rolling their own
HTTP/OpenAI wrappers, so model/base URL/API key can be centrally configured.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Sequence

import requests

from fomc.config import load_env

load_env()


@dataclass
class LLMConfig:
    api_key: Optional[str] = None
    base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    temperature: float = 0.25
    max_tokens: int = 1600
    timeout: int = 60


# Backward-compatible alias for existing code
DeepSeekConfig = LLMConfig


class LLMClient:
    """Minimal chat-completion client for DeepSeek/OpenAI-compatible endpoints."""

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()
        self.api_key = self.config.api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is missing; please set it in .env")

    def chat(
        self,
        messages: Sequence[dict],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        payload = {
            "model": model or self.config.model,
            "messages": list(messages),
            "temperature": temperature if temperature is not None else self.config.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.config.max_tokens,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        url = f"{self.config.base_url.rstrip('/')}/v1/chat/completions"
        resp = requests.post(url, json=payload, headers=headers, timeout=self.config.timeout)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


class DeepSeekClient(LLMClient):
    """Compatibility wrapper: expose .generate for existing callers."""

    def generate(self, messages: Sequence[dict], **kwargs) -> str:
        return self.chat(messages, **kwargs)

