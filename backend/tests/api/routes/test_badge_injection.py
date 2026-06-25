"""Tests for _inject_badge_via_llm helper."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.models import Repository


def test_inject_badge_via_llm_uses_first_available_provider() -> None:
    from app.api.routes.repositories import _inject_badge_via_llm

    mock_result = MagicMock()
    mock_result.content = (
        "# My Project\n[![Badge](http://badge.svg)](http://link)\n\nContent"
    )

    mock_provider = MagicMock()
    mock_provider.generate = AsyncMock(return_value=mock_result)

    repo = MagicMock(spec=Repository)
    repo.llm_provider = None
    repo.llm_model = None
    repo.organization = None

    with (
        patch(
            "app.services.llm.catalog.get_provider",
            return_value=mock_provider,
        ) as mock_get_provider,
        patch(
            "app.services.llm.catalog.get_first_available_provider",
            return_value=("openai", "gpt-4o"),
        ),
    ):
        result = asyncio.run(
            _inject_badge_via_llm(
                "# My Project\n\nContent",
                "[![Badge](http://badge.svg)](http://link)",
                repo,
            )
        )

    assert result is not None
    assert "Badge" in result
    mock_get_provider.assert_called_once()
    mock_provider.generate.assert_awaited_once()


def test_inject_badge_via_llm_uses_repo_provider() -> None:
    from app.api.routes.repositories import _inject_badge_via_llm

    mock_result = MagicMock()
    mock_result.content = "modified readme"

    mock_provider = MagicMock()
    mock_provider.generate = AsyncMock(return_value=mock_result)

    repo = MagicMock(spec=Repository)
    repo.llm_provider = MagicMock()
    repo.llm_provider.value = "anthropic"
    repo.llm_model = "claude-3-haiku-20240307"
    repo.organization = None

    with patch(
        "app.services.llm.catalog.get_provider",
        return_value=mock_provider,
    ) as mock_get_provider:
        result = asyncio.run(_inject_badge_via_llm("readme", "badge", repo))

    assert result == "modified readme"
    mock_get_provider.assert_called_once_with(
        provider="anthropic", model="claude-3-haiku-20240307"
    )


def test_inject_badge_via_llm_uses_org_provider_fallback() -> None:
    from app.api.routes.repositories import _inject_badge_via_llm

    mock_result = MagicMock()
    mock_result.content = "modified readme"

    mock_provider = MagicMock()
    mock_provider.generate = AsyncMock(return_value=mock_result)

    org = MagicMock()
    org.default_llm_provider = MagicMock()
    org.default_llm_provider.value = "openai"
    org.default_llm_model = "gpt-4o-mini"

    repo = MagicMock(spec=Repository)
    repo.llm_provider = None
    repo.llm_model = None
    repo.organization = org

    with patch(
        "app.services.llm.catalog.get_provider",
        return_value=mock_provider,
    ) as mock_get_provider:
        result = asyncio.run(_inject_badge_via_llm("readme", "badge", repo))

    assert result == "modified readme"
    mock_get_provider.assert_called_once_with(provider="openai", model="gpt-4o-mini")
