from __future__ import annotations

import shutil
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1280
HEIGHT = 720
SLIDE_DURATION = 1.8
FPS = 30


@dataclass
class SlideSpec:
    kind: str
    title: str = ""
    subtitle: str = ""
    lines: tuple[str, ...] = ()
    image_path: Path | None = None


class VideoExportError(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def export_story_mp4(
    *,
    story: dict[str, Any],
    image_paths: list[Path],
    music_path: Path,
    output_path: Path,
    slide_duration: float = SLIDE_DURATION,
) -> Path:
    if not ffmpeg_available():
        raise VideoExportError("未检测到 ffmpeg，请先安装：brew install ffmpeg")

    slides = build_slides_from_story(story, image_paths)
    if not slides:
        raise VideoExportError("没有可导出的页面")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="hackson-export-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        rendered_frames: list[Path] = []
        for index, slide in enumerate(slides):
            frame_path = temp_dir / f"slide_{index:03d}.png"
            render_slide_png(slide, frame_path)
            rendered_frames.append(frame_path)

        concat_file = temp_dir / "slides.txt"
        concat_lines: list[str] = []
        for frame_path in rendered_frames:
            concat_lines.append(f"file '{frame_path.as_posix()}'")
            concat_lines.append(f"duration {slide_duration}")
        concat_lines.append(f"file '{rendered_frames[-1].as_posix()}'")
        concat_file.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")

        silent_video = temp_dir / "silent.mp4"
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-vf",
                f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
                f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=0x0b1018",
                "-r",
                str(FPS),
                "-pix_fmt",
                "yuv420p",
                str(silent_video),
            ]
        )

        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(silent_video),
                "-i",
                str(music_path),
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                str(output_path),
            ]
        )

    return output_path


def build_slides_from_story(story: dict[str, Any], image_paths: list[Path]) -> list[SlideSpec]:
    slides: list[SlideSpec] = []
    title = str(story.get("title") or "成长纪念册")
    intro_lines = tuple((story.get("intro") or {}).get("lines") or [])
    slides.append(
        SlideSpec(
            kind="cover",
            title=title,
            subtitle="MEMORY RECAP",
            lines=intro_lines[:3],
        )
    )

    timeline = story.get("timeline") or []
    for index, node in enumerate(timeline):
        image_path = image_paths[index] if index < len(image_paths) else None
        paragraph_lines = tuple((node.get("paragraph") or {}).get("lines") or [])
        slides.append(
            SlideSpec(
                kind="memory",
                title=str(node.get("headline") or node.get("desc") or f"第 {index + 1} 页"),
                subtitle=str(node.get("time") or ""),
                lines=paragraph_lines[:2],
                image_path=image_path if image_path and image_path.exists() else None,
            )
        )

    conclusion_lines = tuple((story.get("conclusion") or {}).get("lines") or [])
    slides.append(
        SlideSpec(
            kind="conclusion",
            title="这一段，被好好保存",
            subtitle="FINAL",
            lines=conclusion_lines[:3],
        )
    )
    return slides


def render_slide_png(slide: SlideSpec, output_path: Path) -> None:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), color=(11, 16, 24))
    draw = ImageDraw.Draw(canvas)

    if slide.kind == "memory" and slide.image_path:
        with Image.open(slide.image_path) as photo:
            photo = photo.convert("RGB")
            photo.thumbnail((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
            offset_x = (WIDTH - photo.width) // 2
            offset_y = (HEIGHT - photo.height) // 2
            canvas.paste(photo, (offset_x, offset_y))
        overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle((0, HEIGHT - 220, WIDTH, HEIGHT), fill=(8, 12, 18, 190))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(canvas)
        draw_text_block(draw, slide, y_start=HEIGHT - 190)
    else:
        draw_gradient_background(draw)
        draw_text_block(draw, slide, y_start=220 if slide.kind == "cover" else 250)

    canvas.save(output_path, format="PNG")


def draw_gradient_background(draw: ImageDraw.ImageDraw) -> None:
    for y in range(HEIGHT):
        ratio = y / max(HEIGHT - 1, 1)
        red = int(11 + ratio * 18)
        green = int(16 + ratio * 28)
        blue = int(24 + ratio * 36)
        draw.line([(0, y), (WIDTH, y)], fill=(red, green, blue))


def draw_text_block(draw: ImageDraw.ImageDraw, slide: SlideSpec, *, y_start: int) -> None:
    title_font = load_font(54)
    subtitle_font = load_font(24)
    body_font = load_font(28)

    y = y_start
    if slide.subtitle:
        draw.text((72, y), slide.subtitle, fill=(69, 214, 255), font=subtitle_font)
        y += 42

    if slide.title:
        for line in wrap_text(slide.title, 16):
            draw.text((72, y), line, fill=(255, 255, 255), font=title_font)
            y += 62

    y += 12
    for line in slide.lines:
        for wrapped in wrap_text(line, 24):
            draw.text((72, y), wrapped, fill=(220, 228, 238), font=body_font)
            y += 38


def wrap_text(text: str, max_chars: int) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    return textwrap.wrap(text, width=max_chars) or [text]


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def run_ffmpeg(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "ffmpeg failed").strip()
        raise VideoExportError(detail[-800:])
