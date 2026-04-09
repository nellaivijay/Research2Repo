"""
OpenAI provider — GPT-4o, GPT-4o-mini, o1, o3, o3-mini support with vision and structured output.
"""

import base64
import json
import os
from typing import Optional

from providers.base import (
    BaseProvider,
    GenerationConfig,
    GenerationResult,
    ModelCapability,
    ModelInfo,
)


class OpenAIProvider(BaseProvider):
    """OpenAI GPT provider with vision and JSON-mode support."""

    MODELS = [
        ModelInfo(
            name="gpt-4o",
            provider="openai",
            max_context_tokens=128_000,
            max_output_tokens=16_384,
            capabilities=[
                ModelCapability.TEXT_GENERATION,
                ModelCapability.VISION,
                ModelCapability.LONG_CONTEXT,
                ModelCapability.STRUCTURED_OUTPUT,
                ModelCapability.CODE_GENERATION,
                ModelCapability.STREAMING,
            ],
            cost_per_1k_input=0.0025,
            cost_per_1k_output=0.01,
        ),
        ModelInfo(
            name="gpt-4o-mini",
            provider="openai",
            max_context_tokens=128_000,
            max_output_tokens=16_384,
            capabilities=[
                ModelCapability.TEXT_GENERATION,
                ModelCapability.VISION,
                ModelCapability.LONG_CONTEXT,
                ModelCapability.STRUCTURED_OUTPUT,
                ModelCapability.CODE_GENERATION,
                ModelCapability.STREAMING,
            ],
            cost_per_1k_input=0.00015,
            cost_per_1k_output=0.0006,
        ),
        ModelInfo(
            name="gpt-4-turbo",
            provider="openai",
            max_context_tokens=128_000,
            max_output_tokens=4_096,
            capabilities=[
                ModelCapability.TEXT_GENERATION,
                ModelCapability.VISION,
                ModelCapability.LONG_CONTEXT,
                ModelCapability.STRUCTURED_OUTPUT,
                ModelCapability.CODE_GENERATION,
                ModelCapability.STREAMING,
            ],
            cost_per_1k_input=0.01,
            cost_per_1k_output=0.03,
        ),
        ModelInfo(
            name="o3",
            provider="openai",
            max_context_tokens=200_000,
            max_output_tokens=100_000,
            capabilities=[
                ModelCapability.TEXT_GENERATION,
                ModelCapability.VISION,
                ModelCapability.LONG_CONTEXT,
                ModelCapability.STRUCTURED_OUTPUT,
                ModelCapability.CODE_GENERATION,
                ModelCapability.STREAMING,
            ],
            cost_per_1k_input=0.01,
            cost_per_1k_output=0.04,
        ),
        ModelInfo(
            name="o3-mini",
            provider="openai",
            max_context_tokens=200_000,
            max_output_tokens=100_000,
            capabilities=[
                ModelCapability.TEXT_GENERATION,
                ModelCapability.LONG_CONTEXT,
                ModelCapability.CODE_GENERATION,
                ModelCapability.STREAMING,
            ],
            cost_per_1k_input=0.0011,
            cost_per_1k_output=0.0044,
        ),
        ModelInfo(
            name="o1",
            provider="openai",
            max_context_tokens=200_000,
            max_output_tokens=100_000,
            capabilities=[
                ModelCapability.TEXT_GENERATION,
                ModelCapability.LONG_CONTEXT,
                ModelCapability.CODE_GENERATION,
            ],
            cost_per_1k_input=0.015,
            cost_per_1k_output=0.06,
        ),
    ]

    # Reasoning models that do not support the "system" message role.
    # System instructions must be folded into the user message instead.
    _REASONING_MODELS = {"o1", "o1-mini", "o1-preview", "o3-mini"}

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError("OPENAI_API_KEY not set.")
        super().__init__(api_key=key, model_name=model_name)

        from openai import OpenAI
        self._client = OpenAI(api_key=self.api_key)

    def default_model(self) -> str:
        return "gpt-4o"

    def available_models(self) -> list[ModelInfo]:
        return self.MODELS

    def _is_reasoning_model(self) -> bool:
        """Check if the current model is a reasoning model that restricts system messages."""
        return self.model_name in self._REASONING_MODELS

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        config: Optional[GenerationConfig] = None,
        images: Optional[list[bytes]] = None,
    ) -> GenerationResult:
        cfg = config or GenerationConfig()
        messages = []

        # Reasoning models (o1, o3-mini, etc.) don't support the "system" role.
        # Fold system instructions into the user message instead.
        if system_prompt and self._is_reasoning_model():
            prompt = f"[System Instructions]\n{system_prompt}\n\n[User Request]\n{prompt}"
            system_prompt = None

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if images and self.supports(ModelCapability.VISION):
            content = [{"type": "text", "text": prompt}]
            for img_bytes in images:
                b64 = base64.b64encode(img_bytes).decode("utf-8")
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                })
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": prompt})

        kwargs = {
            "model": self.model_name,
            "messages": messages,
        }
        # Reasoning models don't support temperature, top_p, or max_tokens
        # (they use max_completion_tokens instead).
        if self._is_reasoning_model():
            kwargs["max_completion_tokens"] = cfg.max_output_tokens
        else:
            kwargs["temperature"] = cfg.temperature
            kwargs["top_p"] = cfg.top_p
            kwargs["max_tokens"] = cfg.max_output_tokens
        if cfg.stop_sequences:
            kwargs["stop"] = cfg.stop_sequences
        if cfg.response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}

        response = self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        usage = response.usage

        return GenerationResult(
            text=choice.message.content or "",
            model=self.model_name,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            finish_reason=choice.finish_reason or "stop",
            raw_response=response,
        )

    def generate_structured(
        self,
        prompt: str,
        schema: dict,
        system_prompt: Optional[str] = None,
        config: Optional[GenerationConfig] = None,
    ) -> dict:
        cfg = config or GenerationConfig()
        cfg.response_format = "json"
        schema_instruction = (
            f"Respond with valid JSON conforming to this schema:\n"
            f"```json\n{json.dumps(schema, indent=2)}\n```\n\n"
        )
        full_prompt = schema_instruction + prompt
        result = self.generate(full_prompt, system_prompt=system_prompt, config=cfg)
        return json.loads(result.text)
