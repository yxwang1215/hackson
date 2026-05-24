from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from app.models import GenerateNarrativeRequest, PhotoItem
from app.services.llm import ImageAsset, LLMConfigError, LLMService


@dataclass
class PreparedImageAsset:
    filename: str
    content_type: str
    data: bytes


class NarrativePipeline:
    def __init__(self, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    async def prepare_items_with_analysis(
        self,
        items: Sequence[PhotoItem],
        images: Sequence[PreparedImageAsset],
    ) -> list[PhotoItem]:
        prepared_items: list[PhotoItem] = []
        for index, item in enumerate(items):
            analysis = item.image_analysis.strip()
            if not analysis:
                analysis = await self._fill_image_analysis(item, images, index)

            prepared_items.append(
                item.model_copy(
                    update={
                        "image_analysis": analysis,
                        "image_filename": item.image_filename or image_name_or_none(images, index),
                        "image_mime_type": item.image_mime_type or mime_type_or_none(images, index),
                    }
                )
            )
        return prepared_items

    async def _fill_image_analysis(
        self,
        item: PhotoItem,
        images: Sequence[PreparedImageAsset],
        index: int,
    ) -> str:
        mode = getattr(self.llm_service.settings, "vision_analysis_mode", "auto").strip().lower()
        local_only = mode in {"local", "skip", "off", "false", "none"}
        force_vlm = mode in {"vlm", "vision", "all"} or should_force_vlm(item)

        if not force_vlm:
            analysis = build_local_image_analysis(item, index, allow_generic=local_only)
            if analysis:
                return analysis

        if local_only:
            return f"第 {index + 1} 张照片保留了一个按时间排列的日常片段。"

        if index >= len(images):
            raise LLMConfigError(f"第 {index + 1} 张图片缺少 image_analysis，且没有可用上传文件")
        image = images[index]
        return await self.llm_service.analyze_image(
            ImageAsset(filename=image.filename, content_type=image.content_type, data=image.data),
            time_hint=item.time,
            desc_hint=item.desc,
        )

    async def generate_from_items(
        self,
        items: Sequence[PhotoItem],
        language: str,
        tone: str,
        max_lines_per_block: int,
    ) -> dict:
        request = GenerateNarrativeRequest(
            items=list(items),
            language=language,
            tone=tone,
            max_lines_per_block=max_lines_per_block,
        )
        return await self.llm_service.generate(request)

    async def generate_from_images(
        self,
        items: Sequence[PhotoItem],
        images: Sequence[PreparedImageAsset],
        language: str,
        tone: str,
        max_lines_per_block: int,
    ) -> dict:
        prepared_items = await self.prepare_items_with_analysis(items, images)
        return await self.generate_from_items(prepared_items, language, tone, max_lines_per_block)


def image_name_or_none(images: Sequence[PreparedImageAsset], index: int) -> str | None:
    if index >= len(images):
        return None
    return images[index].filename or None


def mime_type_or_none(images: Sequence[PreparedImageAsset], index: int) -> str | None:
    if index >= len(images):
        return None
    return images[index].content_type or None


def should_force_vlm(item: PhotoItem) -> bool:
    priority = (item.analysis_priority or "").strip().lower()
    return priority in {"high", "vlm", "vision", "required", "force_vlm"}


def build_local_image_analysis(item: PhotoItem, index: int, allow_generic: bool = False) -> str:
    subject = first_non_empty(item.desc, item.semantic_hint, filename_subject(item.image_filename or ""))
    if not subject:
        if not allow_generic:
            return ""
        subject = f"第 {index + 1} 张照片"

    time_text = first_non_empty(item.time, item.time_label)
    stage_text = (item.stage_label or "").strip()
    context = "，".join(part for part in [stage_text, time_text] if part)

    if context:
        return f"画面记录了{subject}，对应{context}。"
    return f"画面记录了{subject}这一瞬间。"


def first_non_empty(*values: str | None) -> str:
    for value in values:
        text = (value or "").strip()
        if text:
            return text
    return ""


def filename_subject(filename: str) -> str:
    stem = Path(filename).stem.strip()
    if not stem:
        return ""
    normalized = stem.replace("_", " ").replace("-", " ").strip()
    compact = normalized.replace(" ", "").lower()
    generic_prefixes = ("img", "image", "photo", "dsc", "screenshot", "wx_camera", "wechatimg")
    if compact.isdigit() or any(compact == prefix or compact.startswith(prefix) and compact[len(prefix) :].isdigit() for prefix in generic_prefixes):
        return ""
    return normalized
