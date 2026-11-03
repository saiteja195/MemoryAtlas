import pytest

from app.profiles.limits import RateLimiter
from app.profiles.passcodes import (
    burn_hash, hash_passcode, name_key, normalize_name, validate_passcode, verify_passcode)


def test_hash_then_verify_round_trips():
    salt, h = hash_passcode("correct horse")
    assert verify_passcode("correct horse", salt, h)


def test_verify_rejects_wrong_passcode():
    salt, h = hash_passcode("correct horse")
    assert not verify_passcode("battery staple", salt, h)


def test_same_passcode_hashes_differently_each_time():
    a, b = hash_passcode("correct horse"), hash_passcode("correct horse")
    assert a[0] != b[0] and a[1] != b[1]


def test_name_is_normalised_and_keyed_case_insensitively():
    assert normalize_name("  Sai   Teja ") == "Sai Teja"
    assert name_key("  Sai   Teja ") == name_key("SAI teja")
    assert name_key("Ｓai") == name_key("sai")          # full-width S folds under NFKC


def test_name_length_bounds():
    with pytest.raises(ValueError, match="name must be 2 to 40 characters"):
        normalize_name("a")
    with pytest.raises(ValueError, match="name must be 2 to 40 characters"):
        normalize_name("a" * 41)
    with pytest.raises(ValueError):
        normalize_name("   ")
    assert normalize_name("ab") == "ab" and normalize_name("a" * 40) == "a" * 40


def test_passcode_length_bounds():
    for bad in ("12345", "x" * 201):
        with pytest.raises(ValueError, match="passcode must be 6 to 200 characters"):
            validate_passcode(bad)
    validate_passcode("123456")
    validate_passcode("x" * 200)


def test_burn_hash_runs_without_error():
    burn_hash("anything")


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_rate_limiter_allows_up_to_limit_then_blocks():
    rl = RateLimiter(3, 60, Clock())
    assert [rl.allow("ip") for _ in range(4)] == [True, True, True, False]


def test_rate_limiter_window_expires():
    c = Clock()
    rl = RateLimiter(2, 60, c)
    assert rl.allow("ip") and rl.allow("ip") and not rl.allow("ip")
    c.t = 61
    assert rl.allow("ip")


def test_rate_limiter_keys_are_independent():
    rl = RateLimiter(1, 60, Clock())
    assert rl.allow("a") and not rl.allow("a") and rl.allow("b")


def test_blocked_attempts_do_not_extend_the_window():
    c = Clock()
    rl = RateLimiter(1, 60, c)
    assert rl.allow("ip")
    c.t = 30
    assert not rl.allow("ip")
    assert rl.retry_after("ip") == pytest.approx(30)
    c.t = 61
    assert rl.allow("ip")
