"""Targeted tests for the optional ColSmol service integration."""

import asyncio

import httpx

from construction_os.integrations.colsmol import (
    ColSmolSettings,
    check_colsmol_health,
    load_colsmol_settings,
)


def test_load_colsmol_settings_defaults_to_disabled(monkeypatch):
    monkeypatch.delenv("CONSTRUCTION_OS_MULTIVECTOR_ENABLED", raising=False)
    monkeypatch.delenv("COLSMOL_URL", raising=False)
    monkeypatch.delenv("COLSMOL_TIMEOUT_SECONDS", raising=False)

    settings = load_colsmol_settings()

    assert settings.enabled is False
    assert settings.url == "http://colsmol:8000"
    assert settings.timeout_seconds == 10.0


def test_load_colsmol_settings_reads_environment(monkeypatch):
    monkeypatch.setenv("CONSTRUCTION_OS_MULTIVECTOR_ENABLED", "true")
    monkeypatch.setenv("COLSMOL_URL", "http://localhost:8091/")
    monkeypatch.setenv("COLSMOL_TIMEOUT_SECONDS", "2.5")

    settings = load_colsmol_settings()

    assert settings.enabled is True
    assert settings.url == "http://localhost:8091"
    assert settings.timeout_seconds == 2.5


def test_health_is_safe_when_feature_is_disabled():
    result = asyncio.run(
        check_colsmol_health(
            ColSmolSettings(
                enabled=False,
                url="http://colsmol:8000",
                timeout_seconds=1,
            )
        )
    )

    assert result["status"] == "disabled"
    assert result["available"] is False


class _ReadyResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "status": "ready",
            "ready": True,
            "model": "vidore/colSmol-256M",
            "dimension": 128,
        }


class _ReadyClient:
    def __init__(self):
        self.requested_url = None

    async def get(self, url):
        self.requested_url = url
        return _ReadyResponse()


class _UnavailableClient:
    async def get(self, url):
        request = httpx.Request("GET", url)
        raise httpx.ConnectError("connection refused", request=request)


def test_health_reports_ready():
    client = _ReadyClient()
    result = asyncio.run(
        check_colsmol_health(
            ColSmolSettings(
                enabled=True,
                url="http://colsmol:8000",
                timeout_seconds=1,
            ),
            client=client,
        )
    )

    assert result["status"] == "ready"
    assert result["available"] is True
    assert result["detail"]["model"] == "vidore/colSmol-256M"
    assert client.requested_url == "http://colsmol:8000/health"


def test_health_reports_unavailable_without_raising():
    result = asyncio.run(
        check_colsmol_health(
            ColSmolSettings(
                enabled=True,
                url="http://colsmol:8000",
                timeout_seconds=1,
            ),
            client=_UnavailableClient(),
        )
    )

    assert result["status"] == "unavailable"
    assert result["available"] is False
    assert "connection refused" in result["detail"]
