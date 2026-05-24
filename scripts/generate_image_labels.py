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
        description="Generate labels.json for images. Prefer scripts/preprocess_category.py for full preprocessing."
    )
    parser.add_argument("--image-dir", default="image", help="Image directory to scan.")
    parser.add_argument("--out", default="", help="Output JSON path. Defaults to <image-dir>/labels.json.")
    parser.add_argument(
        "--per-category",
        action="store_true",
        help="Scan immediate subdirectories of --image-dir and write labels.json into each category folder.",
    )
    args = parser.parse_args()

    root = project_root()
    image_dir = Path(args.image_dir)
    if not image_dir.is_absolute():
        image_dir = root / image_dir
    if not image_dir.exists():
        raise SystemExit(f"image dir not found: {image_dir}")

    image_root = image_dir if args.per_category else image_dir.parent

    if args.per_category:
        category_dirs = list_category_dirs(image_dir)
        if not category_dirs:
            raise SystemExit(f"no category subdirectories found under: {image_dir}")
        for category_dir in category_dirs:
            write_one(category_dir, category_dir / "labels.json", image_root=image_dir)
        return

    out_path = Path(args.out) if args.out else image_dir / "labels.json"
    if not out_path.is_absolute():
        out_path = root / out_path
    write_one(image_dir, out_path, image_root=image_root)


def write_one(category_dir: Path, out_path: Path, *, image_root: Path) -> None:
    payload = preprocess_category(category_dir, image_root=image_root)
    target = write_preprocessing_json(category_dir, payload, out_path=out_path)
    print(f"wrote {target} with {payload['summary']['image_count']} images")


if __name__ == "__main__":
    main()
