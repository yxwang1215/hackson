from __future__ import annotations

import json
import urllib.request
from pathlib import Path

MIXKIT_CDN = "https://assets.mixkit.co/music/{track_id}/{track_id}.mp3"

DEFAULT_TRACKS = [
    {
        "id": "warm-piano",
        "name": "温柔梦境",
        "filename": "warm-piano.mp3",
        "mood": "warm",
        "artist": "Diego Nava",
        "source": "Mixkit",
        "source_id": "493",
    },
    {
        "id": "soft-ambient",
        "name": "林间精灵",
        "filename": "soft-ambient.mp3",
        "mood": "calm",
        "artist": "Alejandro Magaña",
        "source": "Mixkit",
        "source_id": "139",
    },
    {
        "id": "bright-memory",
        "name": "晴朗婚礼",
        "filename": "bright-memory.mp3",
        "mood": "bright",
        "artist": "Francisco Alvear",
        "source": "Mixkit",
        "source_id": "657",
    },
]


def download_track_file(music_dir: Path, source_id: str, filename: str) -> Path:
    music_dir.mkdir(parents=True, exist_ok=True)
    destination = music_dir / filename
    url = MIXKIT_CDN.format(track_id=source_id)
    with urllib.request.urlopen(url, timeout=120) as response:
        destination.write_bytes(response.read())
    return destination


def write_tracks_manifest(tracks_file: Path, tracks: list[dict[str, str]]) -> None:
    payload = {
        "tracks": [
            {
                "id": track["id"],
                "name": track["name"],
                "filename": track["filename"],
                "mood": track["mood"],
                "artist": track.get("artist", ""),
                "source": track.get("source", ""),
                "source_id": track.get("source_id", ""),
            }
            for track in tracks
        ]
    }
    tracks_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def download_default_tracks(music_dir: Path, tracks_file: Path) -> None:
    for track in DEFAULT_TRACKS:
        destination = music_dir / track["filename"]
        if destination.exists() and destination.stat().st_size > 100_000:
            continue
        download_track_file(music_dir, str(track["source_id"]), str(track["filename"]))
    write_tracks_manifest(tracks_file, DEFAULT_TRACKS)
