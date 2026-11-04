import os
import sqlite3

import pytest
import yaml

from app.capture.audit import media_bytes_on_disk
from app.capture.draft import Draft, DraftField
from app.profiles import seed

from .fakes import FakeLLM
from .test_media_info import jpeg_with_exif, png

ENV = {"DEMO_STAGED_NAME": "Demo Staged", "DEMO_STAGED_PASSCODE": "published-pass",
       "DEMO_REAL_NAME": "Demo Real", "DEMO_REAL_PASSCODE": "published-pass-2"}


def draft_with_gps() -> Draft:
    return Draft(kind="frame", fields=[DraftField(key="when", value="2026-10-29T12:00:00", source="exif",
                                                  confidence="sure")],
                 questions=[], captured_at="2026-10-29T12:00:00", lat=37.77, lon=-122.41,
                 place_name="Blue Door Cafe", perceptions=[{"caption": "a cafe"}], frame_offsets_ms=[0])


def test_strip_gps_clears_coordinates_only():
    d = seed.strip_gps(draft_with_gps())
    assert d.lat is None and d.lon is None
    assert d.place_name == "Blue Door Cafe" and d.captured_at == "2026-10-29T12:00:00"
    assert d.perceptions == [{"caption": "a cafe"}]


def write_manifest(path, files):
    path.write_text(yaml.safe_dump({"files": files}))
    return str(path)


def test_manifest_requires_a_decision_for_every_file(tmp_path):
    m = write_manifest(tmp_path / "manifest.yaml", {"a.jpg": {"where": "Cafe"}})
    with pytest.raises(ValueError, match="b.jpg"):
        seed.load_manifest(m, ["a.jpg", "b.jpg"])
    assert seed.load_manifest(m, ["a.jpg"])["a.jpg"]["where"] == "Cafe"


def test_manifest_accepts_an_explicit_skip(tmp_path):
    m = write_manifest(tmp_path / "manifest.yaml", {"a.jpg": {"skip": True}})
    assert seed.load_manifest(m, ["a.jpg"])["a.jpg"] == {"skip": True}


def test_manifest_rejects_unknown_keys(tmp_path):
    m = write_manifest(tmp_path / "manifest.yaml", {"a.jpg": {"where": "Cafe", "gps": "37,-122"}})
    with pytest.raises(ValueError, match="gps"):
        seed.load_manifest(m, ["a.jpg"])
    m = write_manifest(tmp_path / "m2.yaml", {"a.jpg": {"people": [{"ref": "visible1", "consented": True, "x": 1}]}})
    with pytest.raises(ValueError, match="x"):
        seed.load_manifest(m, ["a.jpg"])


def test_seed_staged_builds_a_snapshot_with_claims(tmp_path):
    out = tmp_path / "out" / "staged.db"
    path = seed.seed("staged", data_dir=str(tmp_path / "data"), out=str(out), env=ENV, llm=FakeLLM(),
                     say=lambda *_: None)
    assert path == str(out) and out.exists()
    conn = sqlite3.connect(str(out))
    assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] > 0
    assert conn.execute("SELECT COALESCE(SUM(media_bytes_retained),0) FROM sources").fetchone()[0] == 0


def test_seed_registers_the_demo_profile_with_its_kind(tmp_path):
    from app.profiles.registry import Registry
    seed.seed("staged", data_dir=str(tmp_path / "data"), out=str(tmp_path / "s.db"), env=ENV, llm=FakeLLM(),
              say=lambda *_: None)
    p = Registry(str(tmp_path / "data" / "profiles.db")).authenticate("Demo Staged", "published-pass")
    assert p.demo_kind == "staged"


def test_seed_needs_the_credentials(tmp_path):
    with pytest.raises(SystemExit, match="DEMO_STAGED_PASSCODE"):
        seed.seed("staged", data_dir=str(tmp_path / "d"), out=str(tmp_path / "s.db"),
                  env={"DEMO_STAGED_NAME": "Demo Staged"}, llm=FakeLLM(), say=lambda *_: None)


def test_register_creates_the_profile_without_content(tmp_path):
    from app.profiles.registry import Registry
    seed.register("real", data_dir=str(tmp_path / "data"), env=ENV, say=lambda *_: None)
    seed.register("real", data_dir=str(tmp_path / "data"), env=ENV, say=lambda *_: None)    # idempotent
    reg = Registry(str(tmp_path / "data" / "profiles.db"))
    p = reg.authenticate("Demo Real", "published-pass-2")
    assert p.demo_kind == "real" and reg.count() == 1
    assert p.onboarded and p.goals                      # reviewers go straight to the dashboard, not onboarding


def make_media(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "cafe.jpg").write_bytes(jpeg_with_exif())
    (media / "note.txt").write_text("Coffee at Blue Door Cafe after the walk")
    return media


def test_seed_real_applies_the_manifest_strips_gps_and_never_copies_media(tmp_path):
    media = make_media(tmp_path)
    write_manifest(media / "manifest.yaml", {
        "cafe.jpg": {"where": "Blue Door Cafe"},
        "note.txt": {"captured_at": "2026-10-12T13:30:00"}})
    out = tmp_path / "snapshots" / "real.db"
    seed.seed("real", data_dir=str(tmp_path / "data"), media_dir=str(media), out=str(out), env=ENV,
              llm=FakeLLM(), say=lambda *_: None)
    conn = sqlite3.connect(str(out))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM sources").fetchall()
    assert rows and all(r["media_bytes_retained"] == 0 for r in rows)
    assert all(r["lat"] is None and r["lon"] is None for r in rows)          # GPS did not reach the snapshot
    assert media_bytes_on_disk(out.parent) == 0 and sorted(os.listdir(out.parent)) == ["real.db"]
    assert media_bytes_on_disk(tmp_path / "data") == 0
    assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] > 0


def test_seed_real_refuses_a_file_missing_a_required_answer(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "pic.png").write_bytes(png())                                     # no EXIF date, no manifest date
    write_manifest(media / "manifest.yaml", {"pic.png": {"where": "Somewhere"}})
    with pytest.raises(SystemExit, match="pic.png"):
        seed.seed("real", data_dir=str(tmp_path / "data"), media_dir=str(media),
                  out=str(tmp_path / "r.db"), env=ENV, llm=FakeLLM(), say=lambda *_: None)
    assert not (tmp_path / "r.db").exists()


def test_seed_real_needs_a_media_directory_with_a_manifest(tmp_path):
    with pytest.raises(SystemExit, match="manifest"):
        seed.seed("real", data_dir=str(tmp_path / "d"), media_dir=str(tmp_path), out=str(tmp_path / "r.db"),
                  env=ENV, llm=FakeLLM(), say=lambda *_: None)
