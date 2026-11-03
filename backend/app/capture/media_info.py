"""Cheap, deterministic checks on uploaded media, done before any model is called.

Nothing here keeps the bytes. `read_exif` never raises: a photo with no metadata is normal.
"""
import io
import wave
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

MAX_AUDIO_SECONDS = 600
ASR_RATES = (16000, 24000)

_EXIF_IFD, _GPS_IFD = 0x8769, 0x8825
_DATETIME_ORIGINAL, _DATETIME = 36867, 306


class MediaError(ValueError):
    """The upload is not something we can read. The message is safe to show the user."""


@dataclass(frozen=True)
class ExifInfo:
    taken_at: str | None    # naive ISO "YYYY-MM-DDTHH:MM:SS"
    lat: float | None
    lon: float | None


def _degrees(value, ref) -> float | None:
    try:
        d, m, s = (float(x) for x in value)
    except (TypeError, ValueError):
        return None
    deg = d + m / 60 + s / 3600
    return -deg if str(ref).upper() in ("S", "W") else deg


def _taken_at(exif: Image.Exif) -> str | None:
    raw = exif.get_ifd(_EXIF_IFD).get(_DATETIME_ORIGINAL) or exif.get(_DATETIME)
    if not isinstance(raw, str):
        return None
    try:
        date, clock = raw.strip().split(" ")
        y, mo, d = date.split(":")
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}T{clock}"
    except ValueError:
        return None


def read_exif(image: bytes) -> ExifInfo:
    try:
        with Image.open(io.BytesIO(image)) as img:
            exif = img.getexif()
            taken = _taken_at(exif)
            gps = exif.get_ifd(_GPS_IFD)
            lat = _degrees(gps.get(2), gps.get(1)) if 2 in gps else None
            lon = _degrees(gps.get(4), gps.get(3)) if 4 in gps else None
    except Exception:       # corrupt or unsupported: no metadata, not an error
        return ExifInfo(None, None, None)
    if lat is None or lon is None:
        lat = lon = None
    return ExifInfo(taken, lat, lon)


def check_image(image: bytes) -> None:
    try:
        with Image.open(io.BytesIO(image)) as img:
            fmt = img.format
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise MediaError("That file is not a readable image. Use a JPEG or PNG.") from None
    if fmt not in ("JPEG", "PNG"):
        raise MediaError(f"{fmt or 'This'} images are not supported. Use a JPEG or PNG.")


def check_wav(audio: bytes) -> float:
    """Return the duration in seconds, or raise MediaError. The speech service accepts only
    mono 16-bit PCM WAV at 16 or 24 kHz, at most 10 minutes."""
    try:
        with wave.open(io.BytesIO(audio), "rb") as w:
            channels, width, rate, frames = (w.getnchannels(), w.getsampwidth(),
                                             w.getframerate(), w.getnframes())
    except (wave.Error, EOFError):
        raise MediaError("That audio is not a WAV file. Record again or choose a WAV file.") from None
    if channels != 1:
        raise MediaError("The audio must be mono.")
    if width != 2:
        raise MediaError("The audio must be 16-bit.")
    if rate not in ASR_RATES:
        raise MediaError("The audio sample rate must be 16000 or 24000 Hz.")
    seconds = frames / rate
    if seconds > MAX_AUDIO_SECONDS:
        raise MediaError("The audio is longer than 10 minutes.")
    return seconds
