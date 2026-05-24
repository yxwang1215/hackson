from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional

import httpx
from dotenv import load_dotenv

from app.models import GenerateNarrativeRequest
from app.prompts import (
    IMAGE_ANALYSIS_SYSTEM_PROMPT,
    OUTPUT_SCHEMA_HINT,
    STYLE_GUIDE,
    SYSTEM_PROMPT,
    build_image_analysis_prompt,
    build_user_prompt,
)

ProviderName = Literal["mock", "domestic_openai_compatible"]


@dataclass
class ImageAsset:
    filename: str
    content_type: str
    data: bytes


@dataclass
class LLMSettings:
    provider: ProviderName
    api_base_url: Optional[str]
    api_key: Optional[str]
    model: str
    vision_model: str
    temperature: float
    max_tokens: int
    vision_temperature: float
    vision_analysis_mode: str


class LLMConfigError(RuntimeError):
    pass


class LLMService:
    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings

    @classmethod
    def from_env(cls) -> "LLMService":
        load_dotenv(override=True)
        provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()
        if provider not in {"mock", "domestic_openai_compatible"}:
            raise LLMConfigError("LLM_PROVIDER 只能是 mock 或 domestic_openai_compatible")

        model = os.getenv("LLM_MODEL", "qwen-plus")
        settings = LLMSettings(
            provider=provider,  # type: ignore[arg-type]
            api_base_url=os.getenv("LLM_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            api_key=os.getenv("LLM_API_KEY"),
            model=model,
            vision_model=os.getenv("VISION_MODEL", model),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4000")),
            vision_temperature=float(os.getenv("VISION_TEMPERATURE", "0.2")),
            vision_analysis_mode=os.getenv("VISION_ANALYSIS_MODE", "auto").strip().lower(),
        )
        return cls(settings)

    async def generate(self, request: GenerateNarrativeRequest) -> dict[str, Any]:
        if self.settings.provider == "mock":
            return self._mock_response(request)
        if self.settings.provider == "domestic_openai_compatible":
            return await self._generate_with_domestic_api(request)
        raise LLMConfigError(f"不支持的 provider: {self.settings.provider}")

    async def analyze_image(self, image: ImageAsset, time_hint: str = "", desc_hint: str = "") -> str:
        if self.settings.provider == "mock":
            return self._mock_image_analysis(image, time_hint=time_hint, desc_hint=desc_hint)
        if self.settings.provider == "domestic_openai_compatible":
            return await self._analyze_with_domestic_api(image, time_hint=time_hint, desc_hint=desc_hint)
        raise LLMConfigError(f"不支持的 provider: {self.settings.provider}")

    def build_prompts(self, request: GenerateNarrativeRequest) -> tuple[str, str]:
        system_prompt = "\n\n".join([SYSTEM_PROMPT, STYLE_GUIDE, OUTPUT_SCHEMA_HINT])
        user_prompt = build_user_prompt(
            items=request.items,
            language=request.language,
            tone=request.tone,
            max_lines_per_block=request.max_lines_per_block,
        )
        return system_prompt, user_prompt

    async def _generate_with_domestic_api(self, request: GenerateNarrativeRequest) -> dict[str, Any]:
        if not self.settings.api_key:
            raise LLMConfigError("缺少 LLM_API_KEY")

        system_prompt, user_prompt = self.build_prompts(request)
        max_tokens = self._narrative_max_tokens(request)
        payload = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.settings.temperature,
            "max_tokens": max_tokens,
        }

        try:
            data = await self._post_json(
                "/chat/completions",
                {
                    **payload,
                    "response_format": {"type": "json_object"},
                },
            )
        except LLMConfigError as exc:
            if not self._is_response_format_unsupported_error(exc):
                raise
            data = await self._post_json("/chat/completions", payload)

        self._raise_if_truncated(data, max_tokens)
        content = self._extract_message_text(data)
        return self._parse_json(self._strip_code_fences(content))

    async def _analyze_with_domestic_api(self, image: ImageAsset, time_hint: str = "", desc_hint: str = "") -> str:
        if not self.settings.api_key:
            raise LLMConfigError("缺少 LLM_API_KEY")

        payload = {
            "model": self.settings.vision_model,
            "messages": [
                {
                    "role": "system",
                    "content": IMAGE_ANALYSIS_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": build_image_analysis_prompt(time_hint, desc_hint)},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": self._build_data_url(image),
                            },
                        },
                    ],
                }
            ],
            "temperature": self.settings.vision_temperature,
            "max_tokens": 200,
        }

        data = await self._post_json("/chat/completions", payload)
        content = self._extract_message_text(data)
        text = self._strip_code_fences(content).strip()
        if not text:
            raise LLMConfigError("图片分析结果为空")
        return text

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.api_base_url:
            raise LLMConfigError("缺少 LLM_API_BASE_URL")
        if not self.settings.api_key:
            raise LLMConfigError("缺少 LLM_API_KEY")

        url = f"{self.settings.api_base_url.rstrip('/')}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(url, headers=headers, json=payload)

        if response.status_code >= 400:
            raise LLMConfigError(f"模型请求失败: {response.status_code} {response.text}")

        return response.json()

    def _extract_message_text(self, data: dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if not choices:
            raise LLMConfigError("模型返回中缺少 choices")

        message = choices[0].get("message") or {}
        content = message.get("content")
        if content is None:
            raise LLMConfigError("模型返回中缺少 message.content")

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            pieces: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    pieces.append(str(block.get("text", "")))
                else:
                    pieces.append(str(block))
            return "".join(pieces)

        return str(content)

    def _parse_json(self, text: str) -> dict[str, Any]:
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            extracted = self._extract_json_object(text)
            if extracted is not None:
                try:
                    return json.loads(extracted)
                except json.JSONDecodeError:
                    pass
            if exc.msg == "Unterminated string starting at":
                raise LLMConfigError(
                    "模型输出被截断，导致 JSON 字符串没有闭合。请调大 LLM_MAX_TOKENS 后重试。"
                ) from exc
            raise LLMConfigError(f"模型输出不是合法 JSON: {exc}") from exc

    def _extract_json_object(self, text: str) -> str | None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        return text[start : end + 1]

    def _narrative_max_tokens(self, request: GenerateNarrativeRequest) -> int:
        estimated_min = 1200 + len(request.items) * 450
        capped_estimate = min(estimated_min, 8000)
        return max(self.settings.max_tokens, capped_estimate)

    def _raise_if_truncated(self, data: dict[str, Any], max_tokens: int) -> None:
        choices = data.get("choices") or []
        if not choices:
            return

        finish_reason = choices[0].get("finish_reason")
        if finish_reason == "length":
            raise LLMConfigError(
                f"模型输出达到 max_tokens={max_tokens} 后被截断。"
                "请调大 LLM_MAX_TOKENS 后重试。"
            )

    def _is_response_format_unsupported_error(self, exc: LLMConfigError) -> bool:
        message = str(exc).lower()
        return "response_format" in message or "unsupported" in message or "not support" in message

    def _strip_code_fences(self, text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 2 and lines[-1].strip().startswith("```"):
                return "\n".join(lines[1:-1]).strip()
        return text

    def _build_data_url(self, image: ImageAsset) -> str:
        mime_type = image.content_type or "image/jpeg"
        encoded = base64.b64encode(image.data).decode("utf-8")
        return f"data:{mime_type};base64,{encoded}"

    def _mock_image_analysis(self, image: ImageAsset, time_hint: str = "", desc_hint: str = "") -> str:
        desc = desc_hint.strip()
        time_text = time_hint.strip()

        if any(keyword in desc for keyword in ["爬", "爬了", "爬行"]):
            action = "孩子趴在地上努力向前爬"
        elif any(keyword in desc for keyword in ["走", "走路", "迈步"]):
            action = "孩子扶着身边的东西慢慢向前走"
        elif any(keyword in desc for keyword in ["站", "站稳"]):
            action = "孩子正试着站稳身体"
        elif any(keyword in desc for keyword in ["笑", "开心", "可爱"]):
            action = "画面里的主角露出轻松自然的表情"
        else:
            action = "画面记录了一个安静而具体的日常瞬间"

        if time_text:
            return f"{action}，整体氛围温和自然，对应{time_text}。"
        return f"{action}，整体氛围温和自然。"

    def _mock_response(self, request: GenerateNarrativeRequest) -> dict[str, Any]:
        items = request.items
        timeline = []
        for idx, item in enumerate(items, start=1):
            time_text = item.time.strip() or f"第 {idx} 张"
            desc_text = item.desc.strip() or self._mock_desc_from_analysis(item.image_analysis, idx)
            headline = self._mock_headline(time_text, desc_text)
            paragraph_lines = self._mock_paragraph_lines(time_text, desc_text, item.image_analysis)
            timeline.append(
                {
                    "index": idx,
                    "time": time_text,
                    "desc": desc_text,
                    "image_analysis": item.image_analysis,
                    "headline": headline,
                    "paragraph": {
                        "lines": paragraph_lines,
                    },
                    "transition_next": "",
                    "tags": self._mock_tags(desc_text, item.image_analysis),
                }
            )

        for idx in range(len(timeline) - 1):
            current_time = timeline[idx]["time"]
            next_time = timeline[idx + 1]["time"]
            timeline[idx]["transition_next"] = self._mock_transition(current_time, next_time)

        first_time = timeline[0]["time"] if timeline else ""
        last_time = timeline[-1]["time"] if timeline else ""
        return {
            "version": "1.0",
            "language": request.language,
            "style": {"tone": request.tone, "pace": "gentle", "emotion_level": "moderate"},
            "title": "成长纪念册",
            "intro": {
                "lines": [
                    f"从 {first_time} 到 {last_time}，一些变化被悄悄记录了下来。" if items else "有些变化，会在回头看时变得清楚。",
                    "它们不喧哗，只是在时间里慢慢长成了现在的样子。",
                ]
            },
            "timeline": timeline,
            "conclusion": {
                "lines": [
                    "这些片段放在一起，就是一段真实而珍贵的成长。",
                    "时间往前走，记忆却在这些细节里慢慢留下来。",
                ]
            },
            "render_hints": {"newline_mode": "line_array", "max_lines_per_block": request.max_lines_per_block, "allow_truncation": False},
        }

    def _mock_desc_from_analysis(self, analysis_text: str, index: int) -> str:
        analysis = analysis_text.strip()
        if analysis:
            return analysis[:28].rstrip("，。") + "。"
        return f"第 {index} 张照片里的日常瞬间"

    def _mock_headline(self, time_text: str, desc_text: str) -> str:
        desc = desc_text.strip()
        if any(keyword in desc for keyword in ["爬", "爬了", "爬行"]):
            return f"{time_text}，第一次向前"
        if any(keyword in desc for keyword in ["走", "走路", "迈步"]):
            return f"{time_text}，开始自己走路"
        if any(keyword in desc for keyword in ["站", "站稳"]):
            return f"{time_text}，稳稳站起来"
        if any(keyword in desc for keyword in ["笑", "开心", "可爱"]):
            return f"{time_text}，一个很轻的笑容"
        return f"{time_text}，这一页的记录"

    def _mock_paragraph_lines(self, time_text: str, desc_text: str, analysis_text: str) -> list[str]:
        desc = desc_text.strip()
        analysis = analysis_text.strip() or "这张照片记录了一个安静而具体的瞬间。"

        first_line = f"{time_text} 这一页，留下了一个很真实的变化。"

        if any(keyword in desc for keyword in ["爬", "爬了", "爬行"]):
            second_line = "小小的身体趴在地上，一点一点往前挪，连动作都带着认真。"
        elif any(keyword in desc for keyword in ["走", "走路", "迈步"]):
            second_line = "扶着身边的东西慢慢前进，脚步虽然还慢，却已经很坚定。"
        elif any(keyword in desc for keyword in ["站", "站稳"]):
            second_line = "在一次次尝试里，站稳这件事开始变得越来越自然。"
        elif any(keyword in desc for keyword in ["笑", "开心", "可爱"]):
            second_line = "画面里那一点轻轻的笑意，让这一刻显得格外柔和。"
        else:
            second_line = f"{desc}，也和画面里的细节一起，把这一刻留了下来。"

        third_line = analysis if len(analysis) <= 42 else analysis[:42].rstrip("，。") + "。"

        return [first_line, second_line, third_line]

    def _mock_tags(self, desc_text: str, analysis_text: str = "") -> list[str]:
        desc = f"{desc_text} {analysis_text}".strip()
        tags = ["成长", "记录"]
        if any(keyword in desc for keyword in ["爬", "爬了", "爬行"]):
            tags.insert(0, "第一次")
        elif any(keyword in desc for keyword in ["走", "走路", "迈步"]):
            tags.insert(0, "前进")
        elif any(keyword in desc for keyword in ["站", "站稳"]):
            tags.insert(0, "尝试")
        elif any(keyword in desc for keyword in ["笑", "开心", "可爱"]):
            tags.insert(0, "笑容")
        return tags[:3]

    def _mock_transition(self, current_time: str, next_time: str) -> str:
        if current_time and next_time:
            return f"从 {current_time} 走到 {next_time}，变化开始变得更清晰。"
        return "时间继续向前，下一页也随之展开。"
