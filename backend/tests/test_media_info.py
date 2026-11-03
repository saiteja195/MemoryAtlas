import io
import wave

import pytest
from PIL import Image

from app.capture.media_info import ExifInfo, MediaError, check_image, check_wav, read_exif


def jpeg_with_exif() -> bytes:
    img = Image.new("RGB", (8, 8), "white")
    exif = Image.Exif()
    exif.get_ifd(0x8769)[36867] = "2026:10:29 12:42:10"          # DateTimeOriginal
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N", (37.0, 46.0, 29.64)                    # 37.7749 N
    gps[3], gps[4] = "W", (122.0, 25.0, 9.84)                    # 122.4194 W
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, "PNG")
    return buf.getvalue()


def wav(seconds: float = 1.0, rate: int = 16000, channels: int = 1, width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x00" * int(seconds * rate) * channels * width)
    return buf.getvalue()


def test_read_exif_time_and_gps():
    info = read_exif(jpeg_with_exif())
    assert info.taken_at == "2026-10-29T12:42:10"
    assert info.lat == pytest.approx(37.7749, abs=1e-3)
    assert info.lon == pytest.approx(-122.4194, abs=1e-3)


def test_read_exif_missing_is_all_none():
    assert read_exif(png()) == ExifInfo(None, None, None)


def test_read_exif_garbage_never_raises():
    assert read_exif(b"nope") == ExifInfo(None, None, None)


def test_check_image_accepts_jpeg_and_png():
    check_image(jpeg_with_exif())
    check_image(png())


def test_check_image_rejects_non_image():
    with pytest.raises(MediaError):
        check_image(b"this is not an image")


def test_check_wav_accepts_mono_16k():
    assert check_wav(wav(1.0)) == pytest.approx(1.0, abs=0.01)


def test_check_wav_accepts_24k():
    assert check_wav(wav(0.5, rate=24000)) == pytest.approx(0.5, abs=0.01)


def test_check_wav_rejects_stereo():
    with pytest.raises(MediaError, match="mono"):
        check_wav(wav(0.2, channels=2))


def test_check_wav_rejects_wrong_rate():
    with pytest.raises(MediaError, match="16000"):
        check_wav(wav(0.2, rate=44100))


def test_check_wav_rejects_8_bit():
    with pytest.raises(MediaError, match="16-bit"):
        check_wav(wav(0.2, width=1))


def test_check_wav_rejects_mp3_bytes():
    with pytest.raises(MediaError, match="WAV"):
        check_wav(b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb" * 50)


def test_check_wav_rejects_over_ten_minutes():
    with pytest.raises(MediaError, match="10 minutes"):
        check_wav(wav(601, rate=16000))
