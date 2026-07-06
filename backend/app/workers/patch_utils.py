import re


def apply_patch(original: str, patch_text: str) -> str | None:
    """Apply a normalized unified diff patch to original text.

    Returns the patched string, or None if any hunk fails to match.
    """
    result = original.split("\n")
    offset = 0

    lines = patch_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("@@"):
            i += 1
            continue
        m = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        i += 1
        if not m:
            continue
        old_start = int(m.group(1)) - 1  # 0-indexed
        hunk_old: list[str] = []
        hunk_new: list[str] = []
        while (
            i < len(lines)
            and not lines[i].startswith("@@")
            and not lines[i].startswith("--- ")
            and not lines[i].startswith("+++ ")
        ):
            hl = lines[i]
            i += 1
            if not hl or hl.startswith("\\"):
                continue
            if hl.startswith("-"):
                hunk_old.append(hl[1:])
            elif hl.startswith("+"):
                hunk_new.append(hl[1:])
            else:
                hunk_old.append(hl[1:])
                hunk_new.append(hl[1:])
        apply_at = old_start + offset
        if result[apply_at : apply_at + len(hunk_old)] != hunk_old:
            return None
        result[apply_at : apply_at + len(hunk_old)] = hunk_new
        offset += len(hunk_new) - len(hunk_old)

    return "\n".join(result)


def restore_trailing_whitespace(original: str, patched: str) -> str:
    """Restore original trailing whitespace on lines that only differ in trailing whitespace.

    LLMs routinely strip trailing whitespace when regenerating file content.
    For lines where the stripped versions are identical, keep the original so
    the delivered diff contains only meaningful changes.
    """
    orig_lines = original.split("\n")
    new_lines = patched.split("\n")
    result = []
    for i, new_line in enumerate(new_lines):
        if (
            i < len(orig_lines)
            and new_line.rstrip() == orig_lines[i].rstrip()
            and new_line != orig_lines[i]
        ):
            result.append(orig_lines[i])
        else:
            result.append(new_line)
    return "\n".join(result)


def normalize_patch(patch: str) -> str:
    """Recompute @@ hunk header line counts from the actual body lines.

    LLMs frequently write correct hunk bodies but wrong counts in the header.
    Recomputing from the body makes the patch valid for any standard diff applier.
    """
    lines = patch.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("@@"):
            out.append(line)
            i += 1
            continue
        m = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$", line)
        i += 1
        body: list[str] = []
        while (
            i < len(lines)
            and not lines[i].startswith("@@")
            and not lines[i].startswith("--- ")
            and not lines[i].startswith("+++ ")
        ):
            body.append(lines[i])
            i += 1
        if not m:
            out.append(line)
            out.extend(body)
            continue
        old_count = 0
        new_count = 0
        for bl in body:
            if not bl or bl.startswith("\\"):
                continue
            if bl.startswith("-"):
                old_count += 1
            elif bl.startswith("+"):
                new_count += 1
            else:
                old_count += 1
                new_count += 1
        out.append(
            f"@@ -{m.group(1)},{old_count} +{m.group(2)},{new_count} @@{m.group(3)}"
        )
        out.extend(body)
    return "\n".join(out)
