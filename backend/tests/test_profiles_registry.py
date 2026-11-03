import pytest

from app.profiles import passcodes, registry as reg
from app.profiles.registry import BadCredentials, Locked, NameTaken, Registry, TooManyProfiles

DAY = 86400.0


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def r(clock):
    return Registry(":memory:", clock=clock)


def test_create_and_authenticate(r):
    p = r.create("Sai Teja", "secret-pass", goals=["trips"])
    assert len(p.profile_id) == 12 and p.name == "Sai Teja" and p.goals == ["trips"]
    assert not p.onboarded and p.demo_kind is None
    assert r.authenticate("  sai   TEJA ", "secret-pass").profile_id == p.profile_id


def test_duplicate_name_differing_only_by_case_is_taken(r):
    r.create("Sai Teja", "secret-pass")
    with pytest.raises(NameTaken):
        r.create("SAI teja", "another-pass")


def test_unknown_name_and_wrong_passcode_raise_the_same_error(r):
    r.create("Sai Teja", "secret-pass")
    errors = []
    for name, code in (("Nobody Here", "secret-pass"), ("Sai Teja", "wrong-pass"), ("x", "secret-pass")):
        with pytest.raises(BadCredentials) as e:
            r.authenticate(name, code)
        errors.append((type(e.value), str(e.value)))
    assert len(set(errors)) == 1 and errors[0][1] == "Wrong name or passcode"


def test_unknown_name_still_burns_a_hash(r, monkeypatch):
    calls = []
    monkeypatch.setattr(reg, "burn_hash", lambda p: calls.append(p))
    with pytest.raises(BadCredentials):
        r.authenticate("Nobody Here", "whatever")
    assert calls == ["whatever"]


def test_five_wrong_passcodes_lock_the_profile(r, clock):
    r.create("Sai Teja", "secret-pass")
    for _ in range(5):
        with pytest.raises(BadCredentials):
            r.authenticate("Sai Teja", "nope-nope")
    with pytest.raises(Locked) as e:
        r.authenticate("Sai Teja", "secret-pass")
    assert e.value.retry_after == pytest.approx(900, abs=1)


def test_lock_expires(r, clock):
    r.create("Sai Teja", "secret-pass")
    for _ in range(5):
        with pytest.raises(BadCredentials):
            r.authenticate("Sai Teja", "nope-nope")
    clock.t += 901
    assert r.authenticate("Sai Teja", "secret-pass").name == "Sai Teja"


def test_locking_one_profile_does_not_lock_another(r):
    r.create("Sai Teja", "secret-pass")
    r.create("Other One", "other-pass")
    for _ in range(5):
        with pytest.raises(BadCredentials):
            r.authenticate("Sai Teja", "nope-nope")
    assert r.authenticate("Other One", "other-pass").name == "Other One"


def test_success_resets_the_failure_count(r):
    r.create("Sai Teja", "secret-pass")
    for _ in range(4):
        with pytest.raises(BadCredentials):
            r.authenticate("Sai Teja", "nope-nope")
    r.authenticate("Sai Teja", "secret-pass")
    for _ in range(4):
        with pytest.raises(BadCredentials):
            r.authenticate("Sai Teja", "nope-nope")
    assert r.authenticate("Sai Teja", "secret-pass")           # still not locked


def test_session_token_is_stored_hashed(r):
    p = r.create("Sai Teja", "secret-pass")
    token = r.start_session(p.profile_id)
    stored = [str(v) for row in r.conn.execute("SELECT * FROM sessions") for v in tuple(row)]
    assert token not in " ".join(stored)
    assert r.profile_for_token(token).profile_id == p.profile_id
    assert r.profile_for_token(token + "x") is None


def test_session_expires_after_30_days(r, clock):
    p = r.create("Sai Teja", "secret-pass")
    token = r.start_session(p.profile_id)
    clock.t += 30 * DAY - 10
    assert r.profile_for_token(token) is not None
    clock.t += 20
    assert r.profile_for_token(token) is None
    assert r.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_end_session(r):
    p = r.create("Sai Teja", "secret-pass")
    token = r.start_session(p.profile_id)
    r.end_session(token)
    assert r.profile_for_token(token) is None


def test_delete_removes_profile_and_sessions(r):
    p = r.create("Sai Teja", "secret-pass")
    token = r.start_session(p.profile_id)
    r.delete(p.profile_id)
    assert r.get(p.profile_id) is None and r.profile_for_token(token) is None
    assert r.count() == 0
    r.create("Sai Teja", "secret-pass")                           # the name is free again


def test_profile_cap(clock):
    r = Registry(":memory:", clock=clock, max_profiles=2)
    r.create("First One", "secret-pass")
    r.create("Second One", "secret-pass")
    with pytest.raises(TooManyProfiles):
        r.create("Third One", "secret-pass")


def test_goals_and_consent_are_saved(r, clock):
    p = r.create("Sai Teja", "secret-pass")
    r.set_goals(p.profile_id, ["trips", "work_meetings"])
    r.accept_consent(p.profile_id)
    got = r.get(p.profile_id)
    assert got.goals == ["trips", "work_meetings"] and got.onboarded and got.consent_at


def test_unknown_goals_are_refused(r):
    with pytest.raises(ValueError):
        r.create("Sai Teja", "secret-pass", goals=["world_domination"])


def test_invalid_name_or_passcode_on_create_raises_value_error(r):
    with pytest.raises(ValueError):
        r.create("x", "secret-pass")
    with pytest.raises(ValueError):
        r.create("Sai Teja", "short")


def test_registry_persists_on_disk(tmp_path, clock):
    path = str(tmp_path / "profiles.db")
    p = Registry(path, clock=clock).create("Sai Teja", "secret-pass")
    assert Registry(path, clock=clock).authenticate("Sai Teja", "secret-pass").profile_id == p.profile_id


def test_unknown_names_lock_like_real_ones(r, clock):
    for _ in range(5):
        with pytest.raises(BadCredentials):
            r.authenticate("Nobody Here", "whatever-1")
    with pytest.raises(Locked) as e:
        r.authenticate("Nobody Here", "whatever-1")
    assert e.value.retry_after == pytest.approx(900, abs=1)
    clock.t += 901
    with pytest.raises(BadCredentials):
        r.authenticate("Nobody Here", "whatever-1")


def test_phantom_lock_table_is_bounded(r, monkeypatch):
    monkeypatch.setattr(reg, "burn_hash", lambda p: None)          # the hashing is not what is under test
    r.PHANTOM_LIMIT = 20
    for i in range(70):
        with pytest.raises(BadCredentials):
            r.authenticate(f"Nobody {i:06d}", "whatever-1")
    assert len(r._phantom) <= r.PHANTOM_LIMIT


def test_demo_profiles_never_lock(r):
    r.create("Demo Staged", "published-pass", demo_kind="staged")      # the passcode is public on purpose
    for _ in range(10):
        with pytest.raises(BadCredentials):
            r.authenticate("Demo Staged", "nope-nope")
    assert r.authenticate("Demo Staged", "published-pass").demo_kind == "staged"
