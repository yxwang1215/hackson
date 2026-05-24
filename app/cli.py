from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.models import GenerateNarrativeRequest, PhotoItem
from app.services.llm import LLMConfigError, LLMService
from app.services.pipeline import NarrativePipeline, PreparedImageAsset


async def main() -> None:
    llm_service = LLMService.from_env()
    pipeline = NarrativePipeline(llm_service)

    count = int(input("请输入图片数量: ").strip())
    items: list[PhotoItem] = []
    images: list[PreparedImageAsset] = []

    for index in range(count):
        print(f"\n第 {index + 1} 张图片")
        time = input("时间: ").strip()
        desc = input("一句话描述: ").strip()
        image_path = input("图片路径: ").strip().strip('"').strip("'")
        image_analysis = input("图片分析（可留空，留空则调用国产视觉模型自动分析）: ").strip()

        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"图片不存在: {image_path}")

        mime_type = _guess_mime_type(path)
        items.append(
            PhotoItem(
                time=time,
                desc=desc,
                image_analysis=image_analysis,
                image_filename=path.name,
                image_mime_type=mime_type,
            )
        )
        images.append(
            PreparedImageAsset(
                filename=path.name,
                content_type=mime_type,
                data=path.read_bytes(),
            )
        )

    request = GenerateNarrativeRequest(items=items)

    try:
        result = await pipeline.generate_from_images(
            items=request.items,
            images=images,
            language=request.language,
            tone=request.tone,
            max_lines_per_block=request.max_lines_per_block,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except LLMConfigError as exc:
        raise SystemExit(f"生成失败: {str(exc)}") from exc


def _guess_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    return "application/octet-stream"


if __name__ == "__main__":
    asyncio.run(main())