"""Disk audit for the zero-raw-media claim."""
from pathlib import Path

MEDIA_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".webm", ".mp4", ".mov",
                  ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp"}


def media_bytes_on_disk(*dirs: str | Path, recursive: bool = True) -> int:
    """Total size of media files under the given directories (0 means none were kept)."""
    total = 0
    for d in dirs:
        root = Path(d)
        if not root.exists():
            continue
        for p in (root.rglob("*") if recursive else root.iterdir()):
            if p.is_file() and p.suffix.lower() in MEDIA_SUFFIXES:
                total += p.stat().st_size
    return total
