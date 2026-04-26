"""Tests for dormy.auth — key hashing + UUID parsing.

DB-touching paths (resolve_or_create_user, get_current_user_id with
ContextVar set) are exercised separately via end-to-end test from CLI.
"""

from __future__ import annotations

from dormy.auth import get_current_user_id, hash_key
from dormy.mcp.auth import current_user_id


def test_hash_key_is_deterministic() -> None:
    assert hash_key("sk-or-v1-abc") == hash_key("sk-or-v1-abc")


def test_hash_key_differs_on_different_inputs() -> None:
    assert hash_key("sk-or-v1-abc") != hash_key("sk-or-v1-xyz")


def test_hash_key_returns_32_hex_chars() -> None:
    h = hash_key("anykey")
    assert len(h) == 32
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_key_handles_empty_string() -> None:
    h = hash_key("")
    assert len(h) == 32
    # SHA256("") known prefix
    assert h.startswith("e3b0c44298fc1c149afbf4c8")


def test_get_current_user_id_returns_none_when_no_context_no_setting() -> None:
    # ContextVar default is None; no settings.user_id env in test process
    # (unless DORMY_USER_ID happens to be set — unlikely in CI).
    from dormy.config import settings

    if not settings.user_id:
        assert get_current_user_id() is None


def test_get_current_user_id_reads_contextvar_when_set() -> None:
    from uuid import UUID

    test_uuid = UUID("00000000-0000-0000-0000-000000000001")
    token = current_user_id.set(test_uuid)
    try:
        assert get_current_user_id() == test_uuid
    finally:
        current_user_id.reset(token)


def test_get_current_user_id_falls_back_to_invalid_setting_returns_none(
    monkeypatch,
) -> None:
    """Malformed DORMY_USER_ID should log warning and return None."""
    from dormy.config import settings

    monkeypatch.setattr(settings, "user_id", "not-a-uuid")
    assert get_current_user_id() is None
