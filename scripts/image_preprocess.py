from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

IMAGE_SUFFIXES = {".avif", ".bmp", ".gif", ".heic", ".heif", ".jpg", ".jpeg", ".png", ".webp"}
GENERIC_FILENAME_PREFIXES = ("img", "image", "photo", "dsc", "screenshot", "wx_camera", "wechatimg")
VLM_PRIORITY_VALUES = {"high", "vlm", "vision", "required", "force_vlm"}


@dataclass(frozen=True)
class ImageTimeSource:
    value: datetime | None
    kind: str


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_category_dir(image_root: Path, category: str) -> Path:
    name = category.strip().strip("/\\")
    if not name:
        raise ValueError("category name is required")

    direct = Path(name)
    if direct.is_dir():
        return direct.resolve()

    under_root = image_root / name
    if under_root.is_dir():
        return under_root.resolve()

    raise FileNotFoundError(f"category folder not found: {name} (looked under {image_root})")


def list_category_dirs(image_root: Path) -> list[Path]:
    if not image_root.is_dir():
        raise FileNotFoundError(f"image root not found: {image_root}")
    return sorted(
        path
        for path in image_root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )


def list_images(category_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in category_dir.rglob("*")
        if path.is_file()
        and path.suffix.lower() in IMAGE_SUFFIXES
        and path.name not in {"labels.json", "preprocessing.json"}
    )


def preprocess_category(category_dir: Path, *, image_root: Path | None = None) -> dict[str, Any]:
    images = list_images(category_dir)
    if not images:
        raise ValueError(f"no images found in {category_dir}")

    root = project_root()
    try:
        category_ref = category_dir.relative_to(root).as_posix()
    except ValueError:
        category_ref = str(category_dir)

    entries = build_preprocessed_entries(category_dir, images)
    vlm_candidates = sum(1 for item in entries if item.get("analysis_priority") in VLM_PRIORITY_VALUES)

    return {
        "version": "1.1",
        "preprocessed": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "image_dir": category_ref,
        "category": category_dir.name,
        "summary": {
            "image_count": len(entries),
            "vlm_candidates": vlm_candidates,
            "local_analysis_ready": len(entries) - vlm_candidates,
        },
        "label_policy": {
            "absolute_time": "Use EXIF capture time when present.",
            "relative_time": "If EXIF is missing, use file modified time and stable path ordering.",
            "semantic_hint": "Derived from filename when it is not a generic camera name.",
            "analysis_priority": "Generic filenames are marked for VLM; others can use local weak analysis.",
            "warning": "Relative labels describe ordering only; they are not factual capture dates.",
        },
        "items": entries,
    }


def write_preprocessing_json(category_dir: Path, payload: dict[str, Any], out_path: Path | None = None) -> Path:
    target = out_path or category_dir / "labels.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def build_preprocessed_entries(category_dir: Path, images: list[Path]) -> list[dict[str, Any]]:
    time_sources = {path: infer_time_source(path) for path in images}
    sorted_images = sorted(images, key=lambda path: sort_key(category_dir, path, time_sources[path]))
    total = len(sorted_images)

    entries: list[dict[str, Any]] = []
    for index, path in enumerate(sorted_images, start=1):
        source = time_sources[path]
        relative_path = path.relative_to(category_dir).as_posix()
        semantic_hint = semantic_hint_from_filename(path.name)
        stage_label = build_stage_label(index, total)
        time_label = build_time_label(index, total)
        analysis_priority = infer_analysis_priority(path.name, semantic_hint)
        tags = build_tags(path.name, semantic_hint)

        entry: dict[str, Any] = {
            "id": make_id(index),
            "path": relative_path,
            "filename": path.name,
            "sequence_index": index,
            "sequence_total": total,
            "time_label": time_label,
            "stage_label": stage_label,
            "display_time": format_display_time(source.value, index),
            "time_source": source.kind,
            "time_value": source.value.isoformat() if source.value else None,
            "sort_confidence": "high" if source.kind == "exif_capture_time" else "medium" if source.kind != "path_order" else "low",
            "semantic_hint": semantic_hint,
            "tags": tags,
            "analysis_priority": analysis_priority,
            "preprocessed_analysis": build_preprocessed_analysis(
                semantic_hint=semantic_hint,
                stage_label=stage_label,
                time_label=time_label,
                index=index,
            ),
            "notes": build_notes(source.kind, semantic_hint, analysis_priority),
        }

        metadata = read_image_metadata(path)
        if metadata:
            entry["metadata"] = metadata

        entries.append(entry)

    return entries


def semantic_hint_from_filename(filename: str) -> str:
    stem = Path(filename).stem.strip()
    if not stem:
        return ""
    normalized = stem.replace("_", " ").replace("-", " ").strip()
    compact = normalized.replace(" ", "").lower()
    if compact.isdigit():
        return ""
    if any(
        compact == prefix or (compact.startswith(prefix) and compact[len(prefix) :].isdigit())
        for prefix in GENERIC_FILENAME_PREFIXES
    ):
        return ""
    return normalized


def infer_analysis_priority(filename: str, semantic_hint: str) -> str:
    if semantic_hint:
        return "normal"
    stem = Path(filename).stem.strip().lower()
    if stem.isdigit() or stem in {"img", "image", "photo", "dsc"}:
        return "vlm"
    return "vlm"


def build_tags(filename: str, semantic_hint: str) -> list[str]:
    tags: list[str] = []
    if semantic_hint:
        tags.append(semantic_hint)

    stem = Path(filename).stem.replace("_", " ").replace("-", " ")
    for part in stem.split():
        part = part.strip()
        if len(part) >= 2 and part not in tags:
            tags.append(part)
    return tags[:6]


def build_preprocessed_analysis(*, semantic_hint: str, stage_label: str, time_label: str, index: int) -> str:
    subject = semantic_hint or f"第 {index} 张"
    context = "，".join(part for part in [stage_label, time_label] if part)
    if context:
        return f"画面记录了{subject}，对应{context}。"
    return f"画面记录了{subject}这一瞬间。"


def format_display_time(value: datetime | None, index: int) -> str:
    if not value:
        return f"第 {index} 张"
    return f"{value.year}年{value.month}月{value.day}日"


def read_image_metadata(path: Path) -> dict[str, Any] | None:
    metadata: dict[str, Any] = {}
    try:
        metadata["file_size_bytes"] = path.stat().st_size
    except OSError:
        return None

    try:
        from PIL import Image
    except ImportError:
        return metadata or None

    try:
        with Image.open(path) as image:
            metadata["width"] = image.width
            metadata["height"] = image.height
            metadata["format"] = image.format
    except Exception:
        pass

    return metadata or None


def infer_time_source(path: Path) -> ImageTimeSource:
    exif_time = read_exif_datetime(path)
    if exif_time:
        return ImageTimeSource(value=exif_time, kind="exif_capture_time")

    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        return ImageTimeSource(value=modified, kind="file_modified_time")
    except OSError:
        return ImageTimeSource(value=None, kind="path_order")


def read_exif_datetime(path: Path) -> datetime | None:
    try:
        from PIL import Image
    except ImportError:
        return None

    try:
        with Image.open(path) as image:
            exif = image.getexif()
    except Exception:
        return None

    for tag in (36867, 36868, 306):
        raw_value = exif.get(tag)
        if not raw_value:
            continue
        parsed = parse_exif_datetime(str(raw_value))
        if parsed:
            return parsed.astimezone()
    return None


def parse_exif_datetime(value: str) -> datetime | None:
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).astimezone()
        except ValueError:
            continue
    return None


def sort_key(category_dir: Path, path: Path, source: ImageTimeSource) -> tuple[Any, str]:
    relative = path.relative_to(category_dir).as_posix()
    if source.value:
        return (source.value, relative)
    return (datetime.max.replace(tzinfo=timezone.utc), relative)


def make_id(index: int) -> str:
    return f"T{index:02d}"


def build_time_label(index: int, total: int) -> str:
    if total <= 1:
        return "T01 / 唯一节点"
    return f"T{index:02d} / 第 {index} 个时间节点"


def build_stage_label(index: int, total: int) -> str:
    if total <= 1:
        return "单节点"
    ratio = (index - 1) / max(total - 1, 1)
    if ratio <= 0.25:
        return "早期"
    if ratio <= 0.7:
        return "中期"
    return "后期"


def build_notes(kind: str, semantic_hint: str, analysis_priority: str) -> str:
    parts: list[str] = []
    if kind == "exif_capture_time":
        parts.append("使用图片 EXIF 拍摄时间排序。")
    elif kind == "file_modified_time":
        parts.append("图片缺少 EXIF 拍摄时间，使用文件修改时间和路径名做相对排序。")
    else:
        parts.append("图片缺少可用时间信息，仅使用路径名做相对排序。")

    if semantic_hint:
        parts.append(f"文件名语义：{semantic_hint}。")
    else:
        parts.append("文件名缺少语义，建议后续走 VLM 补充理解。")

    if analysis_priority in VLM_PRIORITY_VALUES:
        parts.append("analysis_priority=vlm。")
    return " ".join(parts)
