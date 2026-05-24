from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MUSIC_DIR = BASE_DIR / "static" / "music"
TRACKS_FILE = MUSIC_DIR / "tracks.json"


@dataclass(frozen=True)
class MusicTrack:
    id: str
    name: str
    filename: str
    mood: str = ""

    @property
    def path(self) -> Path:
        return MUSIC_DIR / self.filename

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "filename": self.filename,
            "mood": self.mood,
            "url": f"/static/music/{self.filename}",
        }


def list_music_tracks() -> list[MusicTrack]:
    ensure_music_assets()
    if not TRACKS_FILE.exists():
        return []

    try:
        payload = json.loads(TRACKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

    tracks: list[MusicTrack] = []
    for item in payload.get("tracks") or []:
        if not isinstance(item, dict):
            continue
        track_id = str(item.get("id") or "").strip()
        filename = str(item.get("filename") or "").strip()
        if not track_id or not filename:
            continue
        path = MUSIC_DIR / filename
        if not path.exists():
            continue
        tracks.append(
            MusicTrack(
                id=track_id,
                name=str(item.get("name") or track_id),
                filename=filename,
                mood=str(item.get("mood") or ""),
            )
        )
    return tracks


def get_music_track(track_id: str) -> MusicTrack | None:
    track_id = track_id.strip()
    if not track_id:
        return None
    for track in list_music_tracks():
        if track.id == track_id:
            return track
    return None


def _tracks_manifest_has_audio() -> bool:
    if not TRACKS_FILE.exists():
        return False
    try:
        payload = json.loads(TRACKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return False
    for item in payload.get("tracks") or []:
        if not isinstance(item, dict):
            continue
        filename = str(item.get("filename") or "").strip()
        if filename and (MUSIC_DIR / filename).exists():
            return True
    return False


def ensure_music_assets() -> None:
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    if _tracks_manifest_has_audio():
        return

    from app.services.music_download import download_default_tracks

    download_default_tracks(MUSIC_DIR, TRACKS_FILE)
