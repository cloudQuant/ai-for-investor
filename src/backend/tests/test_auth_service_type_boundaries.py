"""Type-boundary and fail-closed tests for authentication service behavior."""

import pytest

from app.services.auth_service import AuthService


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [{}, {"jti": None}, {"jti": 42}, {"jti": ""}, {"jti": []}],
)
async def test_logout_does_not_revoke_missing_or_invalid_jti(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    """Malformed decoded token IDs must fail closed before repository access."""

    def decode_refresh_token(_: str) -> dict[str, object]:
        return payload

    monkeypatch.setattr("app.utils.security.decode_refresh_token", decode_refresh_token)

    service = AuthService()
    revoke_calls: list[str] = []

    async def record_revoke_call(token_id: str) -> bool:
        revoke_calls.append(token_id)
        return True

    monkeypatch.setattr(service, "revoke_refresh_token", record_revoke_call)

    assert await service.logout("opaque-refresh-token") is False
    assert revoke_calls == []


@pytest.mark.asyncio
async def test_logout_revokes_nonempty_string_jti(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid string token ID continues through the existing revocation path."""

    def decode_refresh_token(_: str) -> dict[str, object]:
        return {"jti": "refresh-id"}

    monkeypatch.setattr("app.utils.security.decode_refresh_token", decode_refresh_token)

    service = AuthService()
    revoke_calls: list[str] = []

    async def record_revoke_call(token_id: str) -> bool:
        revoke_calls.append(token_id)
        return True

    monkeypatch.setattr(service, "revoke_refresh_token", record_revoke_call)

    assert await service.logout("opaque-refresh-token") is True
    assert revoke_calls == ["refresh-id"]
