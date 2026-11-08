"""OpenAI-compatible chat client. Local Ollama by default; Vultr Serverless Inference uses the same API
(LLM_BASE_URL=https://api.vultrinference.com/v1, LLM_API_KEY=..., LLM_MODEL=<a tool-calling model>).

Named presets (LLMConfig.preset / run_eval.py --model) cover the models in the comparison. Cloud presets read
their key from the environment and never from the repo; seed is only sent where the provider documents it."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    model: str
    api_key: str
    temperature: float | None = 0.0  # None: not sent (Claude 5 and GPT-5 families reject it)
    seed: int | None = 7
    timeout: float = 300.0
    reasoning_effort: str | None = None  # GPT-5.6 on chat completions only allows tools with "none"

    @classmethod
    def from_env(cls) -> LLMConfig:
        return cls(
            base_url=os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1"),
            model=os.environ.get("LLM_MODEL", "qwen2.5-8k"),
            api_key=os.environ.get("LLM_API_KEY", "ollama"),  # Ollama ignores the key
        )


# name: (base_url, model id, env var holding the key, send seed?)
PRESETS: dict[str, tuple[str, str, str, bool]] = {
    # local, Ollama; the -8k tags are the same weights with num_ctx 8192 (Ollama's default context is smaller)
    "qwen2.5": ("http://localhost:11434/v1", "qwen2.5-8k", "", True),
    "qwen3": ("http://localhost:11434/v1", "qwen3-8k", "", True),
    "llama3.1": ("http://localhost:11434/v1", "llama3.1-8k", "", True),
    "hermes3": ("http://localhost:11434/v1", "hermes3-8k", "", True),
    # Anthropic, through its OpenAI-compatible endpoint
    "haiku-5.5": ("https://api.anthropic.com/v1/", "claude-haiku-5-5", "ANTHROPIC_API_KEY", False),
    "sonnet-5.5": ("https://api.anthropic.com/v1/", "claude-sonnet-5-5", "ANTHROPIC_API_KEY", False),
    "opus-5.5": ("https://api.anthropic.com/v1/", "claude-opus-5-5", "ANTHROPIC_API_KEY", False),
    "fable-5.1": ("https://api.anthropic.com/v1/", "claude-fable-5-1", "ANTHROPIC_API_KEY", False),
    # Astro AI Gateway (Astropods hackathon credit); only reachable inside an `ast project` container,
    # which injects ASTRO_GATEWAY_URL / ASTRO_GATEWAY_API_KEY; the model comes from CF_MODEL or MODEL_DEFAULT
    "astropods": ("", "", "ASTRO_GATEWAY_API_KEY", False),
    # Vultr Serverless Inference (OpenAI-compatible); the model comes from VULTR_MODEL, default a tool-calling model
    "vultr": ("https://api.vultrinference.com/v1", "", "VULTR_INFERENCE_API_KEY", False),
    # OpenAI; the API id of GPT-6 Astra is not confirmed yet, so it must come from ASTRA_MODEL_ID
    "gpt6-astra": ("https://api.openai.com/v1", "", "OPENAI_API_KEY", True),
}


def preset(name: str) -> LLMConfig:
    if name not in PRESETS:
        raise ValueError(f"unknown model preset {name!r}; choose from {', '.join(PRESETS)}")
    base_url, model, key_env, send_seed = PRESETS[name]
    if name == "gpt6-astra":
        model = os.environ.get("ASTRA_MODEL_ID", "")
        if not model:
            raise RuntimeError("set ASTRA_MODEL_ID to the API id of GPT-6 Astra (see your OpenAI model list)")
    if name == "vultr":
        model = os.environ.get("VULTR_MODEL", "qwen3.8-flash-next")
    if name == "astropods":
        base_url = os.environ.get("ASTRO_GATEWAY_URL", "").rstrip("/") + "/v1"
        model = os.environ.get("CF_MODEL") or os.environ.get("MODEL_DEFAULT", "")
        if base_url == "/v1" or not model:
            raise RuntimeError("astropods runs inside `ast project start` (needs ASTRO_GATEWAY_URL and a model)")
    key = os.environ.get(key_env, "") if key_env else "ollama"
    if not key:
        raise RuntimeError(f"{name} needs {key_env} in the environment (.env)")
    # Claude 5-family models reject `temperature`; GPT-5 reasoning models only accept the default
    fixed_sampling = model.startswith(
        ("claude-opus-5", "claude-sonnet-5", "claude-haiku-5", "claude-fable", "gpt-5", "gpt6")
    )
    return LLMConfig(
        base_url=base_url,
        model=model,
        api_key=key,
        seed=7 if send_seed else None,
        temperature=None if fixed_sampling else 0.0,
        reasoning_effort="none" if model.startswith("gpt-5-6") or name == "vultr" else None,  # vultr: left on, qwen3.8 can spend the whole budget thinking and return no answer
    )


class LLM:
    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig.from_env()
        self.client = OpenAI(base_url=self.config.base_url, api_key=self.config.api_key, timeout=self.config.timeout)

    def chat(self, messages: list[dict], tools: list[dict] | None = None, json_mode: bool = False):
        kw: dict[str, Any] = {"model": self.config.model, "messages": messages}
        if self.config.temperature is not None:
            kw["temperature"] = self.config.temperature
        if self.config.reasoning_effort:
            kw["reasoning_effort"] = self.config.reasoning_effort
        if self.config.seed is not None:
            kw["seed"] = self.config.seed
        if tools:
            kw["tools"] = tools
        if json_mode:
            kw["response_format"] = {"type": "json_object"}
        return self.client.chat.completions.create(**kw).choices[0].message
