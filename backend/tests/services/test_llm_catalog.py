"""What the provider catalog does when the file it is pointed at is wrong.

``AI_PROVIDERS_CONFIG`` names a file an operator edits — on the Coolify
deployment, from the Coolify UI, which is what ``deploy/coolify/compose.yml``
mounts it for. So a typo in it is an ordinary event, and every one of these
cases used to be a 500 from ``/organizations/ai-providers`` and a failed fix
generation rather than a degraded catalog.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.services.llm import catalog as catalog_mod
from app.services.llm.catalog import load_provider_catalog

BUNDLED = json.loads(catalog_mod._DEFAULT_CONFIG.read_text())["providers"]


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    """The catalog is read once per process; each case needs its own read."""
    load_provider_catalog.cache_clear()
    yield
    load_provider_catalog.cache_clear()


def _configure(monkeypatch: pytest.MonkeyPatch, path: Path | str | None) -> None:
    monkeypatch.setattr(
        catalog_mod.settings, "AI_PROVIDERS_CONFIG", str(path) if path else None
    )


def _write(path: Path, catalog: Any) -> Path:
    path.write_text(json.dumps(catalog))
    return path


def test_unset_uses_the_bundled_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch, None)

    assert load_provider_catalog() == BUNDLED


def test_configured_file_is_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    override = [
        {
            "id": "openai",
            "name": "OpenAI",
            "default_model": "gpt-4o",
            "models": ["gpt-4o"],
        }
    ]
    _configure(
        monkeypatch,
        _write(tmp_path / "ai_providers.json", {"providers": override}),
    )

    assert load_provider_catalog() == override


def test_missing_file_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure(monkeypatch, tmp_path / "absent.json")

    assert load_provider_catalog() == BUNDLED


def test_directory_at_the_path_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """What a container gets when Docker seeds a missing bind-mount source."""
    directory = tmp_path / "ai_providers.json"
    directory.mkdir()
    _configure(monkeypatch, directory)

    assert load_provider_catalog() == BUNDLED


def test_invalid_json_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "ai_providers.json"
    path.write_text('{"providers": [')
    _configure(monkeypatch, path)

    assert load_provider_catalog() == BUNDLED


def test_empty_file_falls_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Coolify writes an empty file for a file mount with no content."""
    path = tmp_path / "ai_providers.json"
    path.write_text("")
    _configure(monkeypatch, path)

    assert load_provider_catalog() == BUNDLED


def test_missing_providers_key_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure(monkeypatch, _write(tmp_path / "ai_providers.json", {"provider": []}))

    assert load_provider_catalog() == BUNDLED


def test_empty_provider_list_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure(monkeypatch, _write(tmp_path / "ai_providers.json", {"providers": []}))

    assert load_provider_catalog() == BUNDLED


def test_entry_missing_a_field_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The shape callers index without checking: no default_model, no models."""
    _configure(
        monkeypatch,
        _write(
            tmp_path / "ai_providers.json",
            {"providers": [{"id": "openai", "name": "OpenAI"}]},
        ),
    )

    assert load_provider_catalog() == BUNDLED
    assert "default_model" in caplog.text
