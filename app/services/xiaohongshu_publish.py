from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from PIL import Image

from app.services.video_export import VideoExportError, export_story_mp4, ffmpeg_available

XHS_TITLE_MAX_UNITS = 20
XHS_CONTENT_MAX_CHARS = 1000
XHS_MAX_IMAGES = 18
XHS_MIN_WIDTH = 720
XHS_MIN_HEIGHT = 960
CREATOR_CENTER_URL = "https://creator.xiaohongshu.com/publish/publish?source=official"


class XhsPublishError(RuntimeError):
    pass


@dataclass(frozen=True)
class XhsPublishConfig:
    provider: str
    api_url: str
    api_key: str
    public_base_url: str

    @classmethod
    def from_env(cls) -> XhsPublishConfig:
        return cls(
            provider=(os.getenv("XHS_PUBLISH_PROVIDER") or "mock").strip().lower(),
            api_url=(os.getenv("XHS_PUBLISH_API_URL") or "").strip().rstrip("/"),
            api_key=(os.getenv("XHS_PUBLISH_API_KEY") or "").strip(),
            public_base_url=(os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/"),
        )

    @property
    def webhook_enabled(self) -> bool:
        return self.provider == "webhook" and bool(self.api_url and self.api_key)


@dataclass
class XhsPublishResult:
    status: str
    provider: str
    format: str
    title: str
    content: str
    hashtags: list[str] = field(default_factory=list)
    media_urls: list[str] = field(default_factory=list)
    bundle_token: str = ""
    qrcode: str | None = None
    publish_url: str | None = None
    publish_id: str | None = None
    creator_url: str = CREATOR_CENTER_URL
    instructions: str = ""
    video_available: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider,
            "format": self.format,
            "title": self.title,
            "content": self.content,
            "hashtags": self.hashtags,
            "media_urls": self.media_urls,
            "bundle_token": self.bundle_token,
            "qrcode": self.qrcode,
            "publish_url": self.publish_url,
            "publish_id": self.publish_id,
            "creator_url": self.creator_url,
            "instructions": self.instructions,
            "video_available": self.video_available,
        }


def publish_status(config: XhsPublishConfig | None = None) -> dict[str, Any]:
    config = config or XhsPublishConfig.from_env()
    return {
        "available": True,
        "provider": config.provider,
        "webhook_configured": config.webhook_enabled,
        "formats": ["carousel", "video"],
        "ffmpeg_available": ffmpeg_available(),
        "creator_url": CREATOR_CENTER_URL,
    }


def prepare_xiaohongshu_publish(
    *,
    story: dict[str, Any],
    image_paths: list[Path],
    output_dir: Path,
    public_base_url: str,
    publish_format: str = "carousel",
    music_path: Path | None = None,
    slide_duration: float = 1.8,
    config: XhsPublishConfig | None = None,
) -> XhsPublishResult:
    config = config or XhsPublishConfig.from_env()
    publish_format = (publish_format or "carousel").strip().lower()
    if publish_format not in {"carousel", "video"}:
        raise XhsPublishError("format 仅支持 carousel 或 video")

    valid_images = [path for path in image_paths if path.exists()]
    if not valid_images:
        raise XhsPublishError("没有可用于发布的图片")

    title, content, hashtags = build_xhs_copy(story)
    bundle_token = uuid4().hex
    bundle_dir = output_dir / "publish" / bundle_token
    bundle_dir.mkdir(parents=True, exist_ok=True)

    base_url = (public_base_url or config.public_base_url or "").rstrip("/")
    if not base_url:
        raise XhsPublishError("缺少 PUBLIC_BASE_URL，无法生成可访问的素材链接")

    media_urls: list[str] = []
    video_available = False

    if publish_format == "video":
        if not ffmpeg_available():
            raise XhsPublishError("视频发布需要 ffmpeg，请先安装：brew install ffmpeg")
        if not music_path or not music_path.exists():
            raise XhsPublishError("视频发布需要选择背景音乐")
        video_path = bundle_dir / "memory-recap.mp4"
        export_story_mp4(
            story=story,
            image_paths=valid_images,
            music_path=music_path,
            output_path=video_path,
            slide_duration=slide_duration,
        )
        media_urls.append(f"{base_url}/publish/assets/{bundle_token}/memory-recap.mp4")
        cover_path = bundle_dir / "cover.jpg"
        _write_cover_image(valid_images[0], cover_path)
        media_urls.insert(0, f"{base_url}/publish/assets/{bundle_token}/cover.jpg")
        video_available = True
    else:
        exported = _export_carousel_images(valid_images, bundle_dir)
        media_urls = [f"{base_url}/publish/assets/{bundle_token}/{path.name}" for path in exported]

    manifest = {
        "title": title,
        "content": content,
        "hashtags": hashtags,
        "format": publish_format,
        "media_files": [path.name for path in bundle_dir.iterdir() if path.is_file()],
    }
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = XhsPublishResult(
        status="prepared",
        provider=config.provider,
        format=publish_format,
        title=title,
        content=content,
        hashtags=hashtags,
        media_urls=media_urls,
        bundle_token=bundle_token,
        video_available=video_available,
        creator_url=CREATOR_CENTER_URL,
    )

    if config.webhook_enabled:
        webhook_result = _publish_via_webhook(config, result)
        result.status = webhook_result.get("status") or "qr"
        result.qrcode = webhook_result.get("qrcode")
        result.publish_url = webhook_result.get("publish_url") or webhook_result.get("url")
        result.publish_id = webhook_result.get("publish_id") or webhook_result.get("id")
        result.instructions = webhook_result.get(
            "instructions",
            "请使用小红书 App 扫描二维码完成发布。",
        )
    else:
        result.status = "manual"
        result.instructions = (
            "已生成小红书素材包。请复制标题与正文，下载图片或视频后，"
            "打开小红书创作中心上传发布。"
        )

    return result


def build_xhs_copy(story: dict[str, Any]) -> tuple[str, str, list[str]]:
    title = truncate_xhs_title(str(story.get("title") or "成长纪念册"))

    body_parts: list[str] = []
    intro_lines = (story.get("intro") or {}).get("lines") or []
    if intro_lines:
        body_parts.append("\n".join(str(line).strip() for line in intro_lines if str(line).strip()))

    timeline = story.get("timeline") or []
    for index, node in enumerate(timeline, start=1):
        headline = str(node.get("headline") or node.get("desc") or f"第 {index} 页").strip()
        time_label = str(node.get("time") or "").strip()
        paragraph_lines = (node.get("paragraph") or {}).get("lines") or []
        chunk = headline
        if time_label:
            chunk = f"{time_label} · {headline}"
        if paragraph_lines:
            chunk = f"{chunk}\n" + "\n".join(str(line).strip() for line in paragraph_lines[:2] if str(line).strip())
        body_parts.append(chunk)

    conclusion_lines = (story.get("conclusion") or {}).get("lines") or []
    if conclusion_lines:
        body_parts.append("\n".join(str(line).strip() for line in conclusion_lines if str(line).strip()))

    hashtags = collect_story_hashtags(story)
    hashtag_line = " ".join(format_xhs_hashtag(tag) for tag in hashtags[:8])
    content_core = "\n\n".join(part for part in body_parts if part).strip()
    content = content_core
    if hashtag_line:
        content = f"{content_core}\n\n{hashtag_line}".strip() if content_core else hashtag_line

    if len(content) > XHS_CONTENT_MAX_CHARS:
        content = content[: XHS_CONTENT_MAX_CHARS - 1].rstrip() + "…"

    return title, content, hashtags


def collect_story_hashtags(story: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for node in story.get("timeline") or []:
        for tag in node.get("tags") or []:
            clean = str(tag).strip().lstrip("#")
            if clean and clean not in tags:
                tags.append(clean)
    defaults = ["成长记录", "生活碎片", "纪念册"]
    for tag in defaults:
        if tag not in tags:
            tags.append(tag)
    return tags


def format_xhs_hashtag(tag: str) -> str:
    clean = str(tag).strip().lstrip("#")
    if not clean:
        return ""
    return f"#{clean}[话题]#"


def truncate_xhs_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title.strip())
    if not title:
        return "成长纪念册"

    units = 0.0
    kept: list[str] = []
    for char in title:
        weight = 1.0 if ord(char) > 127 else 0.5
        if units + weight > XHS_TITLE_MAX_UNITS:
            break
        kept.append(char)
        units += weight
    result = "".join(kept).strip()
    return result or "成长纪念册"


def _export_carousel_images(image_paths: list[Path], bundle_dir: Path) -> list[Path]:
    exported: list[Path] = []
    for index, source in enumerate(image_paths[:XHS_MAX_IMAGES], start=1):
        target = bundle_dir / f"slide_{index:02d}.jpg"
        _write_xhs_image(source, target)
        exported.append(target)
    return exported


def _write_xhs_image(source: Path, target: Path) -> None:
    with Image.open(source) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        if width < XHS_MIN_WIDTH or height < XHS_MIN_HEIGHT:
            scale = max(XHS_MIN_WIDTH / max(width, 1), XHS_MIN_HEIGHT / max(height, 1))
            rgb = rgb.resize(
                (max(1, int(width * scale)), max(1, int(height * scale))),
                Image.Resampling.LANCZOS,
            )
        rgb.save(target, format="JPEG", quality=90, optimize=True)


def _write_cover_image(source: Path, target: Path) -> None:
    with Image.open(source) as image:
        rgb = image.convert("RGB")
        rgb.thumbnail((1080, 1440), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (1080, 1440), color=(11, 16, 24))
        offset_x = (1080 - rgb.width) // 2
        offset_y = (1440 - rgb.height) // 2
        canvas.paste(rgb, (offset_x, offset_y))
        canvas.save(target, format="JPEG", quality=90, optimize=True)


async def _publish_via_webhook(config: XhsPublishConfig, prepared: XhsPublishResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "video" if prepared.format == "video" else "normal",
        "title": prepared.title,
        "content": prepared.content,
    }
    if prepared.format == "video":
        video_url = next((url for url in prepared.media_urls if url.endswith(".mp4")), "")
        cover_url = next((url for url in prepared.media_urls if url.endswith(".jpg")), "")
        payload["video"] = video_url
        if cover_url:
            payload["cover"] = cover_url
    else:
        payload["images"] = [url for url in prepared.media_urls if url.endswith(".jpg")]

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.api_key}",
        "X-API-Key": config.api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(config.api_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise XhsPublishError(f"小红书发布接口调用失败: {exc}") from exc

    if not isinstance(data, dict):
        raise XhsPublishError("小红书发布接口返回格式异常")

    nested = data.get("data") if isinstance(data.get("data"), dict) else data
    qrcode = nested.get("qrcode") or data.get("qrcode")
    publish_url = nested.get("url") or nested.get("publish_url") or data.get("url")
    publish_id = nested.get("id") or data.get("id")
    status = "qr" if qrcode or publish_url else "submitted"
    return {
        "status": status,
        "qrcode": qrcode,
        "publish_url": publish_url,
        "publish_id": publish_id,
        "instructions": nested.get("instructions") or data.get("instructions") or "",
    }


def resolve_publish_bundle_file(bundle_root: Path, token: str, filename: str) -> Path:
    token = token.strip()
    filename = Path(filename).name
    if not token or not filename or ".." in filename:
        raise XhsPublishError("无效的素材路径")

    bundle_dir = bundle_root / "publish" / token
    path = bundle_dir / filename
    if not path.exists() or not path.is_file():
        raise XhsPublishError("素材不存在")
    return path


def delete_publish_bundle(bundle_root: Path, token: str) -> None:
    bundle_dir = bundle_root / "publish" / token.strip()
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir, ignore_errors=True)
