"""Tests for the comment-preservation guard.

Every fix prompt promises "Preserve ALL existing comments exactly as they appear"
and nothing verified it. Two shipped fix PRs deleted the comment that explained
why the finding they were fixing was not a finding in this repository, and then
made the change the comment argued against.
"""

from app.services.llm.comment_guard import comment_deletion_error, deleted_comments

_DOCKERFILE = """\
# No USER here, deliberately. This image is a local/CI test harness: it is never
# published and never deployed.
FROM node:20
RUN npm ci
"""


def test_a_deleted_rationale_comment_is_rejected() -> None:
    patched = "FROM node:20\nRUN groupadd appuser\nUSER appuser\n"
    error = comment_deletion_error(_DOCKERFILE, patched)
    assert error is not None
    assert "No USER here, deliberately." in error


def test_a_preserved_comment_passes() -> None:
    patched = _DOCKERFILE.replace("RUN npm ci", "RUN npm ci --omit=dev")
    assert comment_deletion_error(_DOCKERFILE, patched) is None


def test_adding_a_comment_is_not_a_deletion() -> None:
    patched = _DOCKERFILE + "# Added by the fix: pin the base image next.\n"
    assert comment_deletion_error(_DOCKERFILE, patched) is None


def test_reindenting_and_rewrapping_a_comment_is_not_a_deletion() -> None:
    """A fix that re-indents a block must not read as erasing its comments."""
    original = "services:\n  # localhost only.\n  adminer:\n    image: adminer\n"
    patched = (
        "services:\n    #    localhost   only.\n    adminer:\n        image: adminer\n"
    )
    assert comment_deletion_error(original, patched) is None


def test_a_file_with_no_comments_is_always_fine() -> None:
    assert comment_deletion_error("FROM node:20\n", "FROM node:22\n") is None


def test_horizontal_rules_and_bare_markers_are_not_comments_worth_failing_over() -> (
    None
):
    original = "#\n#####\nFROM node:20\n"
    assert comment_deletion_error(original, "FROM node:22\n") is None


def test_slash_comments_are_matched_for_hcl() -> None:
    original = (
        '// kept deliberately: the module reads this address\nresource "a" "b" {}\n'
    )
    assert deleted_comments(original, 'resource "a" "b" {}\n') == [
        "kept deliberately: the module reads this address"
    ]


def test_a_trailing_comment_is_not_extracted() -> None:
    """`#` inside a command or a URL fragment is not a comment.

    Telling those apart needs the parser, not a regex, and whole-line comments
    are where the reasoning lives.
    """
    original = "RUN curl https://example.com/x#frag && echo done\n"
    assert deleted_comments(original, "RUN echo done\n") == []


def test_the_error_names_at_most_three_and_counts_the_rest() -> None:
    original = "".join(f"# reason {i}\n" for i in range(6))
    error = comment_deletion_error(original, "FROM node:20\n")
    assert error is not None
    assert "6 comment(s)" in error
    assert "and 3 more" in error
