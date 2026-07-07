"""Unit tests for patch_utils — apply_patch, restore_trailing_whitespace, normalize_patch."""

from app.workers.patch_utils import (
    apply_patch,
    normalize_patch,
    restore_trailing_whitespace,
)

# ─── apply_patch ─────────────────────────────────────────────────────────────


def test_apply_patch_simple_replacement() -> None:
    original = "line1\nline2\nline3\n"
    patch = "--- a/file\n+++ b/file\n@@ -2,1 +2,1 @@\n-line2\n+LINE2\n"
    result = apply_patch(original, patch)
    assert result == "line1\nLINE2\nline3\n"


def test_apply_patch_add_lines() -> None:
    original = "a\nb\nc"
    patch = "--- a/f\n+++ b/f\n@@ -1,2 +1,3 @@\n a\n+inserted\n b\n"
    result = apply_patch(original, patch)
    assert result == "a\ninserted\nb\nc"


def test_apply_patch_delete_lines() -> None:
    original = "a\nb\nc"
    patch = "--- a/f\n+++ b/f\n@@ -2,1 +2,0 @@\n-b\n"
    result = apply_patch(original, patch)
    assert result == "a\nc"


def test_apply_patch_returns_none_on_mismatch() -> None:
    original = "a\nb\nc"
    patch = "--- a/f\n+++ b/f\n@@ -2,1 +2,1 @@\n-WRONG\n+new\n"
    result = apply_patch(original, patch)
    assert result is None


def test_apply_patch_multiple_hunks() -> None:
    original = "a\nb\nc\nd\ne"
    patch = "--- a/f\n+++ b/f\n@@ -1,1 +1,1 @@\n-a\n+A\n@@ -5,1 +5,1 @@\n-e\n+E\n"
    result = apply_patch(original, patch)
    assert result == "A\nb\nc\nd\nE"


def test_apply_patch_skips_non_hunk_lines() -> None:
    # Lines not starting with @@ before any hunk header should be skipped
    original = "hello\nworld"
    patch = "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -1,1 +1,1 @@\n-hello\n+HELLO\n"
    result = apply_patch(original, patch)
    assert result == "HELLO\nworld"


def test_apply_patch_backslash_lines_ignored() -> None:
    # Lines starting with backslash (e.g. "\ No newline at end of file") are ignored
    original = "a\nb"
    patch = "--- a/f\n+++ b/f\n@@ -1,1 +1,1 @@\n-a\n+A\n\\ No newline at end of file\n"
    result = apply_patch(original, patch)
    assert result == "A\nb"


def test_apply_patch_empty_patch() -> None:
    original = "unchanged"
    result = apply_patch(original, "")
    assert result == "unchanged"


def test_apply_patch_hunk_header_no_match_skipped() -> None:
    # @@ line that doesn't match the regex pattern is skipped without crashing
    original = "line"
    patch = "@@ invalid hunk header @@\n-line\n+new\n"
    # Should not raise; returns original joined (no valid hunk applied)
    result = apply_patch(original, patch)
    assert result == "line"


def test_apply_patch_context_lines_preserved() -> None:
    original = "a\nb\nc\nd"
    patch = "--- a/f\n+++ b/f\n@@ -2,3 +2,3 @@\n b\n-c\n+C\n d\n"
    result = apply_patch(original, patch)
    assert result == "a\nb\nC\nd"


# ─── restore_trailing_whitespace ─────────────────────────────────────────────


def test_restore_trailing_whitespace_restores_stripped_space() -> None:
    original = "hello   \nworld"
    patched = "hello\nworld"
    result = restore_trailing_whitespace(original, patched)
    assert result == "hello   \nworld"


def test_restore_trailing_whitespace_keeps_new_content() -> None:
    # When stripped content differs, keep the new line
    original = "hello\nworld"
    patched = "hello\nuniverse"
    result = restore_trailing_whitespace(original, patched)
    assert result == "hello\nuniverse"


def test_restore_trailing_whitespace_no_change_needed() -> None:
    original = "a\nb\nc"
    patched = "a\nb\nc"
    result = restore_trailing_whitespace(original, patched)
    assert result == "a\nb\nc"


def test_restore_trailing_whitespace_new_lines_beyond_original() -> None:
    # Extra lines in patched that have no corresponding original line are kept as-is
    original = "a"
    patched = "a\nb\nc"
    result = restore_trailing_whitespace(original, patched)
    assert result == "a\nb\nc"


def test_restore_trailing_whitespace_tab_trailing() -> None:
    original = "line\t\nend"
    patched = "line\nend"
    result = restore_trailing_whitespace(original, patched)
    assert result == "line\t\nend"


def test_restore_trailing_whitespace_both_identical() -> None:
    original = "same\nlines"
    patched = "same\nlines"
    result = restore_trailing_whitespace(original, patched)
    assert result == "same\nlines"


# ─── normalize_patch ─────────────────────────────────────────────────────────


def test_normalize_patch_fixes_wrong_counts() -> None:
    # Hunk header says 1,1 but body has 2 old / 2 new lines
    patch = "--- a/f\n+++ b/f\n@@ -1,1 +1,1 @@\n-a\n-b\n+A\n+B\n"
    result = normalize_patch(patch)
    assert "@@ -1,2 +1,2 @@" in result


def test_normalize_patch_preserves_non_hunk_lines() -> None:
    patch = "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -1,1 +1,1 @@\n-x\n+y\n"
    result = normalize_patch(patch)
    assert result.startswith("diff --git a/f b/f\n")
    assert "--- a/f" in result
    assert "+++ b/f" in result


def test_normalize_patch_counts_context_lines() -> None:
    patch = "--- a/f\n+++ b/f\n@@ -1,0 +1,0 @@\n a\n-b\n+B\n c\n"
    result = normalize_patch(patch)
    assert "@@ -1,3 +1,3 @@" in result


def test_normalize_patch_add_only_hunk() -> None:
    patch = "--- a/f\n+++ b/f\n@@ -5,0 +5,0 @@\n+new_line\n"
    result = normalize_patch(patch)
    assert "@@ -5,0 +5,1 @@" in result


def test_normalize_patch_delete_only_hunk() -> None:
    patch = "--- a/f\n+++ b/f\n@@ -3,0 +3,0 @@\n-old_line\n"
    result = normalize_patch(patch)
    assert "@@ -3,1 +3,0 @@" in result


def test_normalize_patch_backslash_lines_ignored_in_counts() -> None:
    patch = "--- a/f\n+++ b/f\n@@ -1,0 +1,0 @@\n-a\n+A\n\\ No newline at end of file\n"
    result = normalize_patch(patch)
    assert "@@ -1,1 +1,1 @@" in result


def test_normalize_patch_empty_body_hunk() -> None:
    patch = "--- a/f\n+++ b/f\n@@ -1,5 +1,5 @@\n"
    result = normalize_patch(patch)
    assert "@@ -1,0 +1,0 @@" in result


def test_normalize_patch_preserves_hunk_context_suffix() -> None:
    patch = "--- a/f\n+++ b/f\n@@ -1,1 +1,1 @@ def foo():\n-x\n+y\n"
    result = normalize_patch(patch)
    assert " def foo():" in result


def test_normalize_patch_empty_string() -> None:
    result = normalize_patch("")
    assert result == ""


def test_normalize_patch_no_hunks() -> None:
    patch = "some header\nmore lines\n"
    result = normalize_patch(patch)
    assert result == patch


# ─── YAML-realistic patch tests ──────────────────────────────────────────────
# Snippets derived from the encode/httpx and celery/celery workflow files.

_CHECKOUT_SHA = "11bd71901bbe5b1630ceea73d27597364c9af683"
_SETUP_PYTHON_SHA = "ece7cb06caefa5fff74198d8649806c4678c61a1"

# Minimal steps block representative of httpx_test_suite.yml
_HTTPX_STEPS = (
    "    steps:\n"
    '      - uses: "actions/checkout@v4"\n'
    '      - uses: "actions/setup-python@v6"\n'
    "        with:\n"
    '          python-version: "3.11"\n'
    '      - name: "Run tests"\n'
    '        run: "scripts/test"\n'
)


def test_pin_single_action_ref_in_yaml() -> None:
    """apply_patch replaces a single mutable action ref with a full SHA."""
    clean_diff = (
        "--- a/.github/workflows/test-suite.yml\n"
        "+++ b/.github/workflows/test-suite.yml\n"
        "@@ -2,1 +2,1 @@\n"
        '-      - uses: "actions/checkout@v4"\n'
        f'+      - uses: "actions/checkout@{_CHECKOUT_SHA}"  # v4\n'
    )
    result = apply_patch(_HTTPX_STEPS, clean_diff)
    assert result is not None
    assert _CHECKOUT_SHA in result
    assert "checkout@v4" not in result
    # Non-targeted lines are preserved as-is
    assert "setup-python@v6" in result


def test_multi_hunk_pins_two_actions_in_yaml() -> None:
    """Two-hunk diff pins checkout and setup-python in separate hunks."""
    diff = (
        "--- a/.github/workflows/test-suite.yml\n"
        "+++ b/.github/workflows/test-suite.yml\n"
        "@@ -2,1 +2,1 @@\n"
        '-      - uses: "actions/checkout@v4"\n'
        f'+      - uses: "actions/checkout@{_CHECKOUT_SHA}"  # v4\n'
        "@@ -3,1 +3,1 @@\n"
        '-      - uses: "actions/setup-python@v6"\n'
        f'+      - uses: "actions/setup-python@{_SETUP_PYTHON_SHA}"  # v6\n'
    )
    result = apply_patch(_HTTPX_STEPS, diff)
    assert result is not None
    assert _CHECKOUT_SHA in result
    assert _SETUP_PYTHON_SHA in result
    assert "checkout@v4" not in result
    assert "setup-python@v6" not in result


def test_yaml_indentation_preserved_after_patch() -> None:
    """Two-space YAML indentation is preserved through a targeted line replacement."""
    original = (
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v7\n"
        "      - run: make test\n"
    )
    clean_diff = (
        "--- a/ci.yml\n"
        "+++ b/ci.yml\n"
        "@@ -5,1 +5,1 @@\n"
        "-      - uses: actions/checkout@v7\n"
        f"+      - uses: actions/checkout@{_CHECKOUT_SHA}  # v7\n"
    )
    result = apply_patch(original, clean_diff)
    assert result is not None
    # 6-space indentation preserved for the patched line
    assert f"      - uses: actions/checkout@{_CHECKOUT_SHA}" in result
    # Other lines with their exact indentation preserved
    assert "  build:\n" in result
    assert "    runs-on: ubuntu-latest\n" in result


def test_normalize_then_apply_roundtrip_llm_yaml_diff() -> None:
    """normalize_patch corrects wrong LLM hunk counts; apply_patch then succeeds."""
    # LLM emits wrong counts: header says 1,1 but body has 2 old and 2 new lines
    llm_diff = (
        "--- a/.github/workflows/test-suite.yml\n"
        "+++ b/.github/workflows/test-suite.yml\n"
        "@@ -2,1 +2,1 @@\n"
        '-      - uses: "actions/checkout@v4"\n'
        '-      - uses: "actions/setup-python@v6"\n'
        f'+      - uses: "actions/checkout@{_CHECKOUT_SHA}"  # v4\n'
        f'+      - uses: "actions/setup-python@{_SETUP_PYTHON_SHA}"  # v6\n'
    )
    normalized = normalize_patch(llm_diff)
    assert "@@ -2,2 +2,2 @@" in normalized

    result = apply_patch(_HTTPX_STEPS, normalized)
    assert result is not None, "Normalized patch should apply cleanly"
    assert _CHECKOUT_SHA in result
    assert _SETUP_PYTHON_SHA in result
    assert "checkout@v4" not in result
    assert "setup-python@v6" not in result
