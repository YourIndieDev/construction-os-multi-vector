"""Targeted tests for the optional Qdrant MVP integration."""

import asyncio

import httpx

from construction_os.integrations.qdrant import (
    QdrantSettings,
    check_qdrant_health,
    load_qdrant_settings,
)


def test_load_qdrant_settings_defaults_to_disabled(monkeypatch):
    monkeypatch.delenv("CONSTRUCTION_OS_MULTIVECTOR_ENABLED", raising=False)
    monkeypatch.delenv("QDRANT_URL", raising=False)
    monkeypatch.delenv("QDRANT_TIMEOUT_SECONDS", raising=False)

    settings = load_qdrant_settings()

    assert settings.enabled is False
    assert settings.url == "http://qdrant:6333"
    assert settings.timeout_seconds == 5.0


def test_load_qdrant_settings_reads_environment(monkeypatch):
    monkeypatch.setenv("CONSTRUCTION_OS_MULTIVECTOR_ENABLED", "true")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333/")
    monkeypatch.setenv("QDRANT_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("QDRANT_API_KEY", "secret")

    settings = load_qdrant_settings()

    assert settings.enabled is True
    assert settings.url == "http://localhost:6333"
    assert settings.timeout_seconds == 2.5
    assert settings.api_key == "secret"


def test_health_is_safe_when_feature_is_disabled():
    result = asyncio.run(
        check_qdrant_health(
            QdrantSettings(
                enabled=False,
                url="http://qdrant:6333",
                timeout_seconds=1,
                api_key=None,
            )
        )
    )

    assert result["status"] == "disabled"
    assert result["available"] is False


class _ReadyResponse:
    text = "qdrant is ready"

    def raise_for_status(self):
        return None


class _ReadyClient:
    def __init__(self):
        self.requested_url = None
        self.requested_headers = None

    async def get(self, url, headers=None):
        self.requested_url = url
        self.requested_headers = headers
        return _ReadyResponse()


class _UnavailableClient:
    async def get(self, url, headers=None):
        request = httpx.Request("GET", url, headers=headers)
        raise httpx.ConnectError("connection refused", request=request)


def test_health_reports_ready_and_uses_api_key():
    client = _ReadyClient()
    result = asyncio.run(
        check_qdrant_health(
            QdrantSettings(
                enabled=True,
                url="http://qdrant:6333",
                timeout_seconds=1,
                api_key="secret",
            ),
            client=client,
        )
    )

    assert result["status"] == "ready"
    assert result["available"] is True
    assert client.requested_url == "http://qdrant:6333/readyz"
    assert client.requested_headers == {"api-key": "secret"}


def test_health_reports_unavailable_without_raising():
    result = asyncio.run(
        check_qdrant_health(
            QdrantSettings(
                enabled=True,
                url="http://qdrant:6333",
                timeout_seconds=1,
                api_key=None,
            ),
            client=_UnavailableClient(),
        )
    )

    assert result["status"] == "unavailable"
    assert result["available"] is False
    assert "connection refused" in result["detail"]
