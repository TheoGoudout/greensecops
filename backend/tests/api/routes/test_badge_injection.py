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


# ─── where the badge lands ───────────────────────────────────────────────────

BADGE = "[![GreenSecOps](https://gso.example/b.svg)](https://gso.example/r)"


def test_badge_joins_an_existing_row() -> None:
    """The bug: the badge went on its own line *above* the row it belonged in.

    A README's badges are almost always one row on one line, and that row is
    where a new badge goes — that is what the LLM prompt asks for, and what the
    fallback has to do too when the LLM is unavailable.
    """
    from app.api.routes.repositories import _insert_badge_simple

    readme = (
        "# scio\n"
        "\n"
        "[![CI](https://ci.example/b.svg)](https://ci.example) "
        "[![PyPI](https://pypi.example/b.svg)](https://pypi.example)\n"
        "\n"
        "A description.\n"
    )
    result = _insert_badge_simple(readme, BADGE)

    badge_line = next(line for line in result.splitlines() if BADGE in line)
    # On the row, not on a line of its own above it.
    assert "[![CI]" in badge_line and "[![PyPI]" in badge_line
    assert badge_line.endswith(BADGE)
    assert result.endswith("A description.\n")


def test_badges_stacked_one_per_line_gain_another_line() -> None:
    """Some READMEs put each badge on its own line; keep that shape."""
    from app.api.routes.repositories import _insert_badge_simple

    readme = (
        "# scio\n"
        "\n"
        "[![CI](https://ci.example/b.svg)](https://ci.example)\n"
        "[![PyPI](https://pypi.example/b.svg)](https://pypi.example)\n"
        "\n"
        "A description.\n"
    )
    result = _insert_badge_simple(readme, BADGE)

    lines = result.splitlines()
    assert lines.index(BADGE) == lines.index(
        "[![PyPI](https://pypi.example/b.svg)](https://pypi.example)"
    ) + 1


def test_no_badges_falls_back_to_after_the_heading() -> None:
    from app.api.routes.repositories import _insert_badge_simple

    readme = "# scio\n\nA description.\n"
    result = _insert_badge_simple(readme, BADGE)

    assert result == f"# scio\n\n{BADGE}\n\nA description.\n"


def test_no_heading_puts_the_badge_at_the_top() -> None:
    from app.api.routes.repositories import _insert_badge_simple

    readme = "A description with no heading.\n"
    assert _insert_badge_simple(readme, BADGE).startswith(BADGE)


def test_prose_containing_an_image_is_not_a_badge_row() -> None:
    """Appending to it would drop the badge into the middle of a sentence."""
    from app.api.routes.repositories import _insert_badge_simple

    readme = "# scio\n\nSee the ![diagram](d.png) for details.\n"
    result = _insert_badge_simple(readme, BADGE)

    assert "See the ![diagram](d.png) for details.\n" in result
    assert f"# scio\n\n{BADGE}\n" in result


# ─── what counts as "only the badge was added" ───────────────────────────────


def test_badge_added_to_a_row_is_accepted() -> None:
    """The check that was rejecting every good answer.

    It demanded a pure line insertion, so a badge joining a row — a change to
    that line — always failed, and the fallback ran instead. That is how the
    badge ended up on a line of its own.
    """
    from app.api.routes.repositories import _badge_only_added

    original = "# scio\n\n[![CI](c.svg)](c)\n\nText.\n"
    modified = f"# scio\n\n[![CI](c.svg)](c) {BADGE}\n\nText.\n"

    assert _badge_only_added(original, modified, BADGE) is True


def test_badge_on_its_own_line_is_accepted() -> None:
    from app.api.routes.repositories import _badge_only_added

    original = "# scio\n\nText.\n"
    modified = f"# scio\n\n{BADGE}\n\nText.\n"

    assert _badge_only_added(original, modified, BADGE) is True


def test_a_normalised_trailing_newline_is_accepted() -> None:
    """A model that adds or drops the final newline has still only added the badge."""
    from app.api.routes.repositories import _badge_only_added

    original = "# scio\n\nText."
    modified = f"# scio\n\n{BADGE}\n\nText.\n"

    assert _badge_only_added(original, modified, BADGE) is True


def test_output_without_the_badge_is_rejected() -> None:
    from app.api.routes.repositories import _badge_only_added

    assert _badge_only_added("# scio\n", "# scio\n\nSomething else.\n", BADGE) is False


def test_deleted_content_is_rejected() -> None:
    from app.api.routes.repositories import _badge_only_added

    original = "# scio\n\nKeep me.\n\nAnd me.\n"
    modified = f"# scio\n\n{BADGE}\n\nKeep me.\n"

    assert _badge_only_added(original, modified, BADGE) is False


def test_reworded_content_is_rejected() -> None:
    """The whole point of the check: the model must not edit the README."""
    from app.api.routes.repositories import _badge_only_added

    original = "# scio\n\nA scientific IO library.\n"
    modified = f"# scio\n\n{BADGE}\n\nA library for scientific IO.\n"

    assert _badge_only_added(original, modified, BADGE) is False
