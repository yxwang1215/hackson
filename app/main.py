from __future__ import annotations

import json
import mimetypes
import os
from datetime import datetime
from pathlib import Path
from typing import List
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.models import GenerateNarrativeRequest, GenerateNarrativeResponse, PhotoItem
from app.services.llm import LLMConfigError, LLMService
from app.services.music_library import get_music_track, list_music_tracks
from app.services.pipeline import NarrativePipeline, PreparedImageAsset
from app.services.video_export import VideoExportError, export_story_mp4, ffmpeg_available
from app.services.xiaohongshu_publish import (
    XhsPublishError,
    prepare_xiaohongshu_publish,
    publish_status,
    resolve_publish_bundle_file,
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
PROJECT_DIR = BASE_DIR.parent
IMAGE_SUFFIXES = {".avif", ".bmp", ".gif", ".heic", ".heif", ".jpg", ".jpeg", ".png", ".webp"}
folder_asset_registry: dict[str, list[Path]] = {}
upload_asset_registry: dict[str, list[Path]] = {}
folder_label_registry: dict[str, dict[str, dict[str, str]]] = {}
EXPORT_CACHE_DIR = PROJECT_DIR / ".export_cache"

app = FastAPI(title="AI Time Narrative Backend", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

llm_service = LLMService.from_env()
pipeline = NarrativePipeline(llm_service)


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/folder-assets/{token}/{image_index}", include_in_schema=False)
async def folder_asset(token: str, image_index: int) -> FileResponse:
    return _serve_asset_registry(folder_asset_registry, token, image_index)


@app.get("/upload-assets/{token}/{image_index}", include_in_schema=False)
async def upload_asset(token: str, image_index: int) -> FileResponse:
    return _serve_asset_registry(upload_asset_registry, token, image_index)


def _serve_asset_registry(registry: dict[str, list[Path]], token: str, image_index: int) -> FileResponse:
    paths = registry.get(token)
    if not paths or image_index < 0 or image_index >= len(paths):
        raise HTTPException(status_code=404, detail="图片不存在")

    path = paths[image_index]
    if not path.exists() or path.suffix.lower() not in IMAGE_SUFFIXES:
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(path)


@app.get("/export/music-tracks")
async def export_music_tracks() -> dict:
    tracks = [track.to_dict() for track in list_music_tracks()]
    return {"tracks": tracks, "ffmpeg_available": ffmpeg_available()}


@app.post("/export/mp4")
async def export_mp4(
    story_json: str = Form(...),
    music_id: str = Form(...),
    asset_token: str = Form(""),
    asset_source: str = Form(""),
    slide_duration: float = Form(1.8),
) -> FileResponse:
    try:
        story = json.loads(story_json)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"story_json 解析失败: {str(exc)}") from exc

    track = get_music_track(music_id)
    if not track:
        raise HTTPException(status_code=400, detail="未找到所选背景音乐")

    image_paths = resolve_export_image_paths(asset_token=asset_token.strip(), asset_source=asset_source.strip())
    if not image_paths:
        raise HTTPException(status_code=400, detail="没有可用于导出的图片")

    EXPORT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    output_path = EXPORT_CACHE_DIR / f"{uuid4().hex}.mp4"
    normalized_slide_duration = max(0.5, min(10.0, float(slide_duration)))

    try:
        export_story_mp4(
            story=story,
            image_paths=image_paths,
            music_path=track.path,
            output_path=output_path,
            slide_duration=normalized_slide_duration,
        )
    except VideoExportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"视频导出失败: {str(exc)}") from exc

    filename = f"{story.get('title') or 'memory-recap'}.mp4"
    safe_filename = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(filename))
    return FileResponse(
        output_path,
        media_type="video/mp4",
        filename=safe_filename or "memory-recap.mp4",
    )


@app.get("/publish/xiaohongshu/status")
async def xiaohongshu_publish_status() -> dict:
    return publish_status()


@app.get("/publish/assets/{token}/{filename}", include_in_schema=False)
async def publish_asset(token: str, filename: str) -> FileResponse:
    try:
        path = resolve_publish_bundle_file(EXPORT_CACHE_DIR, token, filename)
    except XhsPublishError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


@app.post("/publish/xiaohongshu")
async def publish_xiaohongshu(
    request: Request,
    story_json: str = Form(...),
    asset_token: str = Form(...),
    asset_source: str = Form("folder"),
    publish_format: str = Form("carousel"),
    music_id: str = Form(""),
    slide_duration: float = Form(1.8),
) -> dict:
    try:
        story = json.loads(story_json)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"story_json 解析失败: {str(exc)}") from exc

    image_paths = resolve_export_image_paths(asset_token=asset_token.strip(), asset_source=asset_source.strip())
    if not image_paths:
        raise HTTPException(status_code=400, detail="没有可用于发布的图片")

    music_path = None
    if publish_format.strip().lower() == "video":
        if not music_id.strip():
            raise HTTPException(status_code=400, detail="视频发布需要选择背景音乐")
        track = get_music_track(music_id.strip())
        if not track:
            raise HTTPException(status_code=400, detail="未找到所选背景音乐")
        music_path = track.path

    EXPORT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    normalized_slide_duration = max(0.5, min(10.0, float(slide_duration)))

    try:
        result = prepare_xiaohongshu_publish(
            story=story,
            image_paths=image_paths,
            output_dir=EXPORT_CACHE_DIR,
            public_base_url=resolve_public_base_url(request),
            publish_format=publish_format,
            music_path=music_path,
            slide_duration=normalized_slide_duration,
        )
    except XhsPublishError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except VideoExportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"小红书发布准备失败: {str(exc)}") from exc

    return result.to_dict()


def resolve_public_base_url(request: Request) -> str:
    configured = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    return str(request.base_url).rstrip("/")


def resolve_export_image_paths(*, asset_token: str, asset_source: str) -> list[Path]:
    if not asset_token:
        return []
    if asset_source == "upload":
        paths = upload_asset_registry.get(asset_token) or []
    else:
        paths = folder_asset_registry.get(asset_token) or upload_asset_registry.get(asset_token) or []
    return [path for path in paths if path.exists()]


@app.post("/narrative/generate", response_model=GenerateNarrativeResponse)
async def generate_narrative(request: GenerateNarrativeRequest) -> GenerateNarrativeResponse:
    if not request.items:
        raise HTTPException(status_code=400, detail="items 不能为空")
    if any(not item.image_analysis.strip() for item in request.items):
        raise HTTPException(status_code=400, detail="JSON 生成接口要求每个条目都已经提供 image_analysis；如需上传图片自动分析，请使用 /narrative/generate-upload")

    try:
        result = await llm_service.generate(request)
        return GenerateNarrativeResponse.model_validate(result)
    except LLMConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"生成失败: {str(exc)}") from exc


@app.post("/narrative/generate-upload", response_model=GenerateNarrativeResponse)
async def generate_narrative_upload(
    items_json: str = Form(...),
    images: List[UploadFile] = File(default=[]),
    language: str = Form("zh-CN"),
    tone: str = Form("warm"),
    max_lines_per_block: int = Form(3),
) -> GenerateNarrativeResponse:
    try:
        items_payload = json.loads(items_json)
        request = GenerateNarrativeRequest.model_validate(
            {
                "items": items_payload,
                "language": language,
                "tone": tone,
                "max_lines_per_block": max_lines_per_block,
            }
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"items_json 解析失败: {str(exc)}") from exc

    try:
        prepared_images: list[PreparedImageAsset] = []
        for upload in images:
            data = await upload.read()
            prepared_images.append(
                PreparedImageAsset(
                    filename=upload.filename or "image",
                    content_type=upload.content_type or "image/jpeg",
                    data=data,
                )
            )

        result = await pipeline.generate_from_images(
            items=request.items,
            images=prepared_images,
            language=request.language,
            tone=request.tone,
            max_lines_per_block=request.max_lines_per_block,
        )

        token = uuid4().hex
        cache_dir = EXPORT_CACHE_DIR / token
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached_paths: list[Path] = []
        for index, image in enumerate(prepared_images):
            safe_name = Path(image.filename or f"image_{index}.jpg").name
            path = cache_dir / safe_name
            path.write_bytes(image.data)
            cached_paths.append(path)
        upload_asset_registry[token] = cached_paths

        render_hints = dict(result.get("render_hints") or {})
        render_hints["asset_token"] = token
        render_hints["asset_source"] = "upload"
        render_hints["source_images"] = [f"/upload-assets/{token}/{index}" for index in range(len(cached_paths))]
        result["render_hints"] = render_hints
        return GenerateNarrativeResponse.model_validate(result)
    except LLMConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"图片上传生成失败: {str(exc)}") from exc


@app.post("/narrative/generate-folder", response_model=GenerateNarrativeResponse)
async def generate_narrative_folder(
    folder_path: str = Form(...),
    language: str = Form("zh-CN"),
    tone: str = Form("warm"),
    max_lines_per_block: int = Form(3),
) -> GenerateNarrativeResponse:
    folder = resolve_folder_path(folder_path)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"文件夹不存在: {folder}")

    image_paths = find_image_paths(folder)
    if not image_paths:
        raise HTTPException(status_code=400, detail="该文件夹下没有可识别的图片")

    try:
        label_map = load_folder_labels(folder)
        items: list[PhotoItem] = []
        prepared_images: list[PreparedImageAsset] = []
        for index, image_path in enumerate(image_paths, start=1):
            relative_name = str(image_path.relative_to(folder))
            label_info = label_map.get(relative_name, {})
            semantic_hint = label_info.get("semantic_hint") or describe_from_filename(relative_name)
            items.append(
                PhotoItem(
                    time=format_image_time(image_path, index),
                    desc=semantic_hint,
                    image_analysis="",
                    time_label=label_info.get("time_label"),
                    stage_label=label_info.get("stage_label"),
                    semantic_hint=semantic_hint,
                    analysis_priority=label_info.get("analysis_priority"),
                    image_filename=relative_name,
                    image_mime_type=guess_image_mime_type(image_path),
                )
            )
            prepared_images.append(
                PreparedImageAsset(
                    filename=relative_name,
                    content_type=guess_image_mime_type(image_path),
                    data=image_path.read_bytes(),
                )
            )

        result = await pipeline.generate_from_images(
            items=items,
            images=prepared_images,
            language=language,
            tone=tone,
            max_lines_per_block=max_lines_per_block,
        )

        token = uuid4().hex
        folder_asset_registry[token] = image_paths
        folder_label_registry[token] = label_map
        render_hints = dict(result.get("render_hints") or {})
        render_hints["asset_token"] = token
        render_hints["asset_source"] = "folder"
        render_hints["source_images"] = [f"/folder-assets/{token}/{index}" for index in range(len(image_paths))]
        render_hints["source_folder"] = str(folder)
        result["render_hints"] = render_hints
        return GenerateNarrativeResponse.model_validate(result)
    except LLMConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"文件夹分析失败: {str(exc)}") from exc


def resolve_folder_path(raw_path: str) -> Path:
    path_text = raw_path.strip().strip("\"'")
    if not path_text:
        raise HTTPException(status_code=400, detail="文件夹地址不能为空")
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = PROJECT_DIR / path
    return path.resolve()


def find_image_paths(folder: Path) -> list[Path]:
    paths = [
        path
        for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and not path.name.startswith(".")
    ]
    return sorted(paths, key=lambda path: str(path.relative_to(folder)).lower())


def load_folder_labels(folder: Path) -> dict[str, dict[str, str]]:
    label_file = folder / "labels.json"
    if not label_file.exists():
        return {}

    try:
        data = json.loads(label_file.read_text(encoding="utf-8"))
    except Exception:
        return {}

    items = data.get("items") or []
    image_dir_name = Path(str(data.get("image_dir") or "")).name
    label_map: dict[str, dict[str, str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        path_text = str(item.get("path") or "").strip()
        if not path_text:
            continue
        label_info = {
            "time_label": str(item.get("time_label") or ""),
            "stage_label": str(item.get("stage_label") or ""),
            "semantic_hint": str(item.get("semantic_hint") or ""),
            "analysis_priority": str(item.get("analysis_priority") or "normal"),
        }
        for key in label_lookup_keys(path_text, image_dir_name):
            label_map[key] = label_info
    return label_map


def label_lookup_keys(path_text: str, image_dir_name: str = "") -> set[str]:
    normalized = path_text.strip().replace("\\", "/").lstrip("./")
    keys = {normalized}
    parts = [part for part in normalized.split("/") if part]
    if len(parts) > 1:
        keys.add("/".join(parts[1:]))
    if image_dir_name and parts and parts[0] == image_dir_name:
        keys.add("/".join(parts[1:]))
    if parts:
        keys.add(parts[-1])
    return {key for key in keys if key}


def describe_from_filename(filename: str) -> str:
    stem = Path(filename).stem.strip()
    if not stem:
        return ""
    normalized = stem.replace("_", " ").replace("-", " ").strip()
    compact = normalized.replace(" ", "").lower()
    generic_prefixes = ("img", "image", "photo", "dsc", "screenshot", "wx_camera", "wechatimg")
    if compact.isdigit() or any(compact == prefix or compact.startswith(prefix) and compact[len(prefix) :].isdigit() for prefix in generic_prefixes):
        return ""
    return normalized


def guess_image_mime_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "image/jpeg"


def format_image_time(path: Path, index: int) -> str:
    try:
        captured_at = datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return f"第 {index} 张"
    return f"{captured_at.year}年{captured_at.month}月{captured_at.day}日"
