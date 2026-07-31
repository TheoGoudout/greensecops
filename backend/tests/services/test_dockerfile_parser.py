from app.services.docker.dockerfile_parser import parse_dockerfile_content


def _instructions(parsed: dict, keyword: str) -> list[dict]:
    return [i for i in parsed["instructions"] if i["instruction"] == keyword]


def test_parses_instructions_and_source_lines() -> None:
    raw = "FROM python:3.12-slim\nRUN echo hi\n"
    parsed = parse_dockerfile_content("Dockerfile", raw)
    assert parsed is not None
    assert parsed["__docker_file"] == "Dockerfile"
    run = _instructions(parsed, "RUN")[0]
    assert run["value"] == "echo hi"
    assert run["__start_line__"] == 2
    assert run["__end_line__"] == 2


def test_folds_line_continuations_into_one_instruction() -> None:
    # The span must cover every physical line, so a finding highlights the
    # whole command rather than only the line the backslash started on.
    raw = "FROM debian:12\nRUN apt-get update && \\\n    apt-get install -y curl && \\\n    rm -rf /var/lib/apt/lists/*\n"
    parsed = parse_dockerfile_content("Dockerfile", raw)
    assert parsed is not None
    run = _instructions(parsed, "RUN")[0]
    assert run["value"] == (
        "apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*"
    )
    assert run["__start_line__"] == 2
    assert run["__end_line__"] == 4


def test_comments_inside_a_continuation_do_not_end_the_instruction() -> None:
    raw = "FROM debian:12\nRUN apt-get update && \\\n# a comment Docker ignores\n    apt-get install -y curl\n"
    parsed = parse_dockerfile_content("Dockerfile", raw)
    assert parsed is not None
    assert len(_instructions(parsed, "RUN")) == 1
    assert _instructions(parsed, "RUN")[0]["value"] == (
        "apt-get update && apt-get install -y curl"
    )


def test_honours_the_escape_directive() -> None:
    # `# escape=` swaps the continuation character; with a backtick escape a
    # trailing backslash is literal text, not a continuation.
    raw = "# escape=`\nFROM debian:12\nRUN echo one `\n  && echo two\n"
    parsed = parse_dockerfile_content("Dockerfile", raw)
    assert parsed is not None
    assert parsed["escape"] == "`"
    assert _instructions(parsed, "RUN")[0]["value"] == "echo one && echo two"


def test_records_the_syntax_directive() -> None:
    raw = "# syntax=docker/dockerfile:1\nFROM debian:12\n"
    parsed = parse_dockerfile_content("Dockerfile", raw)
    assert parsed is not None
    assert parsed["syntax"] == "docker/dockerfile:1"


def test_a_plain_comment_closes_the_directive_section() -> None:
    # Docker only honours parser directives before the first non-directive
    # line, so an escape directive after a comment is inert.
    raw = "# just a comment\n# escape=`\nFROM debian:12\n"
    parsed = parse_dockerfile_content("Dockerfile", raw)
    assert parsed is not None
    assert parsed["escape"] == "\\"


def test_captures_flags_separately_from_the_command() -> None:
    raw = "FROM debian:12\nRUN --mount=type=cache,target=/root/.cache pip install -r requirements.txt\n"
    parsed = parse_dockerfile_content("Dockerfile", raw)
    assert parsed is not None
    run = _instructions(parsed, "RUN")[0]
    assert run["flags"] == {"mount": "type=cache,target=/root/.cache"}
    assert run["value"] == "pip install -r requirements.txt"


def test_reads_heredoc_bodies() -> None:
    raw = "FROM debian:12\nRUN <<EOF\napt-get update\napt-get install -y curl\nEOF\nUSER app\n"
    parsed = parse_dockerfile_content("Dockerfile", raw)
    assert parsed is not None
    run = _instructions(parsed, "RUN")[0]
    assert run["heredoc"] == "apt-get update\napt-get install -y curl"
    assert run["__start_line__"] == 2
    assert run["__end_line__"] == 5
    # The instruction after the heredoc terminator is still parsed.
    assert _instructions(parsed, "USER")[0]["__start_line__"] == 6


def test_reads_quoted_and_dash_heredoc_markers() -> None:
    raw = "FROM debian:12\nRUN <<-'EOF'\n\techo quoted\n\tEOF\n"
    parsed = parse_dockerfile_content("Dockerfile", raw)
    assert parsed is not None
    assert "echo quoted" in _instructions(parsed, "RUN")[0]["heredoc"]


def test_tracks_multistage_boundaries_and_marks_the_final_stage() -> None:
    raw = (
        "FROM golang:1.23 AS builder\n"
        "RUN go build ./...\n"
        "\n"
        "FROM gcr.io/distroless/static\n"
        "COPY --from=builder /app /app\n"
    )
    parsed = parse_dockerfile_content("Dockerfile", raw)
    assert parsed is not None
    assert [s["name"] for s in parsed["stages"]] == ["builder", None]
    assert [s["is_final"] for s in parsed["stages"]] == [False, True]
    assert parsed["final_stage"] == 1
    # A stage ends where the next begins, so a builder-scoped rule reports the
    # right span.
    assert parsed["stages"][0]["__start_line__"] == 1
    assert parsed["stages"][0]["__end_line__"] == 3
    copy = _instructions(parsed, "COPY")[0]
    assert copy["stage"] == 1
    assert copy["flags"] == {"from": "builder"}


def test_splits_image_tag_digest_and_stage_name() -> None:
    raw = "FROM python:3.12-slim@sha256:abc123 AS base\n"
    parsed = parse_dockerfile_content("Dockerfile", raw)
    assert parsed is not None
    stage = parsed["stages"][0]
    assert stage["image"] == "python"
    assert stage["tag"] == "3.12-slim"
    assert stage["digest"] == "sha256:abc123"
    assert stage["name"] == "base"


def test_instructions_before_the_first_from_have_no_stage() -> None:
    # A global ARG is legal before any FROM and belongs to no stage.
    raw = "ARG PYTHON_VERSION=3.12\nFROM python:${PYTHON_VERSION}\n"
    parsed = parse_dockerfile_content("Dockerfile", raw)
    assert parsed is not None
    assert _instructions(parsed, "ARG")[0]["stage"] is None


def test_instruction_keywords_are_normalised_to_uppercase() -> None:
    parsed = parse_dockerfile_content("Dockerfile", "from debian:12\nuser app\n")
    assert parsed is not None
    assert [i["instruction"] for i in parsed["instructions"]] == ["FROM", "USER"]


def test_returns_none_when_there_are_no_instructions() -> None:
    assert parse_dockerfile_content("Dockerfile", "") is None
    assert parse_dockerfile_content("Dockerfile", "# only a comment\n") is None


def test_blank_lines_before_a_directive_are_skipped() -> None:
    parsed = parse_dockerfile_content(
        "Dockerfile", "\n\n# syntax=docker/dockerfile:1\nFROM debian:12\n"
    )
    assert parsed is not None
    assert parsed["syntax"] == "docker/dockerfile:1"


def test_a_line_that_is_not_an_instruction_is_skipped() -> None:
    # Defensive: a stray line must not abort the file, the rest of which is
    # still worth scanning.
    parsed = parse_dockerfile_content(
        "Dockerfile", "FROM debian:12\n!!! garbage\nUSER app\n"
    )
    assert parsed is not None
    assert [i["instruction"] for i in parsed["instructions"]] == ["FROM", "USER"]


def test_an_unparseable_from_still_yields_a_stage() -> None:
    # The stage must exist even when the reference cannot be split, or every
    # final-stage rule would silently stop firing on the file.
    parsed = parse_dockerfile_content("Dockerfile", "FROM \n")
    assert parsed is not None
    assert len(parsed["stages"]) == 1
    assert parsed["stages"][0]["is_final"] is True
