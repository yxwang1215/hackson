#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from image_preprocess import (  # noqa: E402
    list_category_dirs,
    preprocess_category,
    project_root,
    resolve_category_dir,
    write_preprocessing_json,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preprocess an image category under image/ and write labels.json."
    )
    parser.add_argument(
        "category",
        nargs="?",
        help="Category folder name or path, e.g. life or image/life",
    )
    parser.add_argument(
        "--image-root",
        default="image",
        help="Root image directory. Default: image",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Preprocess every immediate subdirectory under --image-root.",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Optional output path. Defaults to <category>/labels.json",
    )
    args = parser.parse_args()

    root = project_root()
    image_root = Path(args.image_root)
    if not image_root.is_absolute():
        image_root = root / image_root

    if args.all:
        category_dirs = list_category_dirs(image_root)
        if not category_dirs:
            raise SystemExit(f"no category folders found under {image_root}")
        for category_dir in category_dirs:
            run_one(category_dir, image_root=image_root, out_path=None)
        return

    if not args.category:
        parser.error("category is required unless --all is set")

    category_dir = resolve_category_dir(image_root, args.category)
    out_path = Path(args.out) if args.out else None
    if out_path and not out_path.is_absolute():
        out_path = root / out_path
    run_one(category_dir, image_root=image_root, out_path=out_path)


def run_one(category_dir: Path, *, image_root: Path, out_path: Path | None) -> None:
    payload = preprocess_category(category_dir, image_root=image_root)
    target = write_preprocessing_json(category_dir, payload, out_path=out_path)
    summary = payload["summary"]
    print(
        f"preprocessed {category_dir.name}: "
        f"{summary['image_count']} images, "
        f"{summary['local_analysis_ready']} local-ready, "
        f"{summary['vlm_candidates']} vlm -> {target}"
    )


if __name__ == "__main__":
    main()
