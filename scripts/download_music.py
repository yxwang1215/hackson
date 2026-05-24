#!/usr/bin/env python3
"""Download default Mixkit light-music tracks into app/static/music/."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.music_download import download_default_tracks

MUSIC_DIR = ROOT / "app" / "static" / "music"
TRACKS_FILE = MUSIC_DIR / "tracks.json"


def main() -> None:
    download_default_tracks(MUSIC_DIR, TRACKS_FILE)
    print(f"Music tracks ready in {MUSIC_DIR}")


if __name__ == "__main__":
    main()
