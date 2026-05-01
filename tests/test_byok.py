"""Tests for dormy.telegram.byok — per-user OpenRouter key management."""

from __future__ import annotations

import pytest

from dormy.telegram.byok import (
    BYOKError,
    KEY_PREFIX,
    mask_key,
    validate_openrouter_key,
)


# --- mask_key ---


def test_mask_none_returns_placeholder() -> None:
    assert mask_key(None) == "(none)"
    assert mask_key("") == "(none)"


def test_mask_short_key_truncates_safely() -> None:
    out = mask_key("short")
    # Don't expose the whole key even if it's short.
    assert "…" in out or len(out) <= 6


def test_mask_real_shape_shows_prefix_and_suffix() -> None:
    key = "sk-or-v1-abc123def456ghi789jklmno"
    out = mask_key(key)
    assert out.startswith("sk-or-v1-abc")
    assert out.endswith("lmno")
    assert "…" in out


# --- validate_openrouter_key ---


@pytest.mark.asyncio
async def test_validate_rejects_wrong_prefix() -> None:
    with pytest.raises(BYOKError) as ei:
        await validate_openrouter_key("openai-sk-not-correct")
    assert KEY_PREFIX in str(ei.value)


@pytest.mark.asyncio
async def test_validate_rejects_invalid_key_via_http(monkeypatch) -> None:
    """Mock httpx.AsyncClient.get to return a 401 — should raise BYOKError."""
    import httpx

    class FakeResp:
        status_code = 401

        def json(self) -> dict:
            return {"error": "invalid"}

    class FakeClient:
        def __init__(self, *_a, **_kw) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_a) -> None:
            return None

        async def get(self, *_a, **_kw) -> FakeResp:
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    with pytest.raises(BYOKError) as ei:
        await validate_openrouter_key(KEY_PREFIX + "abcdefg")
    msg = str(ei.value).lower()
    assert "invalid" in msg or "rejected" in msg or "revoked" in msg


@pytest.mark.asyncio
async def test_validate_returns_data_on_200(monkeypatch) -> None:
    import httpx

    class FakeResp:
        status_code = 200

        def json(self) -> dict:
            return {"data": {"label": "Test", "usage": 1.23, "limit": 10.0}}

    class FakeClient:
        def __init__(self, *_a, **_kw) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_a) -> None:
            return None

        async def get(self, *_a, **_kw) -> FakeResp:
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    out = await validate_openrouter_key(KEY_PREFIX + "abcdefg")
    assert out["label"] == "Test"
    assert out["usage"] == 1.23
    assert out["limit"] == 10.0


@pytest.mark.asyncio
async def test_validate_handles_network_error(monkeypatch) -> None:
    import httpx

    class FakeClient:
        def __init__(self, *_a, **_kw) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_a) -> None:
            return None

        async def get(self, *_a, **_kw):  # noqa: ANN201
            raise httpx.ConnectError("DNS down")

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    with pytest.raises(BYOKError) as ei:
        await validate_openrouter_key(KEY_PREFIX + "abcdefg")
    assert "openrouter" in str(ei.value).lower() or "reach" in str(ei.value).lower()


@pytest.mark.asyncio
async def test_validate_handles_non_json(monkeypatch) -> None:
    import httpx

    class FakeResp:
        status_code = 200

        def json(self):  # noqa: ANN201
            raise ValueError("not json")

    class FakeClient:
        def __init__(self, *_a, **_kw) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_a) -> None:
            return None

        async def get(self, *_a, **_kw) -> FakeResp:
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    with pytest.raises(BYOKError) as ei:
        await validate_openrouter_key(KEY_PREFIX + "abcdefg")
    assert "json" in str(ei.value).lower()


@pytest.mark.asyncio
async def test_validate_handles_missing_data_field(monkeypatch) -> None:
    import httpx

    class FakeResp:
        status_code = 200

        def json(self) -> dict:
            return {"unexpected_shape": True}

    class FakeClient:
        def __init__(self, *_a, **_kw) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_a) -> None:
            return None

        async def get(self, *_a, **_kw) -> FakeResp:
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    with pytest.raises(BYOKError) as ei:
        await validate_openrouter_key(KEY_PREFIX + "abcdefg")
    assert "data" in str(ei.value).lower() or "field" in str(ei.value).lower()
