"""GitHub host / install URL resolution, including bare GH_HOST values."""

from __future__ import annotations

import pytest

import quality_gates.host as host

ENV_KEYS = ("GH_HOST", "GITHUB_SERVER_URL", "GITHUB_API_URL", "GH_API")


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_defaults_are_public_github(clean_env: pytest.MonkeyPatch) -> None:
    assert host.html_base() == "https://github.com"
    assert host.api_base() == "https://api.github.com"
    assert host.install_url().startswith("https://github.com/apps/")


def test_gh_host_is_bare_host_without_scheme(clean_env: pytest.MonkeyPatch) -> None:
    # `gh` and the Copilot app set GH_HOST=github.com, which has no scheme.
    clean_env.setenv("GH_HOST", "github.com")
    assert host.html_base() == "https://github.com"
    assert host.install_url().startswith("https://github.com/")


def test_gh_host_trailing_slash_is_trimmed(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("GH_HOST", "github.com/")
    assert host.html_base() == "https://github.com"


def test_enterprise_gh_host_gets_scheme(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("GH_HOST", "github.mycorp.com")
    assert host.html_base() == "https://github.mycorp.com"
    assert host.is_github_enterprise() is False


def test_github_server_url_takes_precedence_and_keeps_scheme(
    clean_env: pytest.MonkeyPatch,
) -> None:
    clean_env.setenv("GITHUB_SERVER_URL", "https://github.ie")
    clean_env.setenv("GH_HOST", "github.com")
    assert host.html_base() == "https://github.ie"


def test_enterprise_api_v3_derives_html_base(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("GH_API", "https://github.mycorp.com/api/v3")
    assert host.html_base() == "https://github.mycorp.com"
    assert host.is_github_enterprise() is True


def test_marketplace_falls_back_to_install_on_enterprise(
    clean_env: pytest.MonkeyPatch,
) -> None:
    clean_env.setenv("GH_API", "https://github.mycorp.com/api/v3")
    assert host.marketplace_url() == host.install_url()


def test_marketplace_url_on_dotcom(clean_env: pytest.MonkeyPatch) -> None:
    assert host.marketplace_url() == ("https://github.com/marketplace/the-code-sheriff")


def test_app_identity_has_absolute_urls(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("GH_HOST", "github.com")
    identity = host.app_identity()
    assert identity["install_url"].startswith("https://")
    assert identity["marketplace_url"].startswith("https://")
