import json

import pytest

from app.services.docker.merge import (
    COMPOSE,
    DOCKERFILE,
    classify_docker_file,
    is_override_file,
    merge_docker_files,
)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("Dockerfile", DOCKERFILE),
        ("backend/Dockerfile", DOCKERFILE),
        ("Dockerfile.prod", DOCKERFILE),
        ("prod.Dockerfile", DOCKERFILE),
        ("Containerfile", DOCKERFILE),
        ("compose.yml", COMPOSE),
        ("compose.yaml", COMPOSE),
        ("compose.override.yml", COMPOSE),
        ("docker-compose.yml", COMPOSE),
        ("deploy/docker-compose.test.yaml", COMPOSE),
        # Documentation about a Dockerfile is not one.
        ("Dockerfile.md", None),
        ("README.md", None),
        ("compose.json", None),
        ("main.tf", None),
        ("", None),
    ],
)
def test_classify_docker_file(path: str, expected: str | None) -> None:
    assert classify_docker_file(path) == expected


def test_merge_splits_dockerfiles_from_compose_files() -> None:
    merged = merge_docker_files(
        [
            ("backend/Dockerfile", "FROM python:3.12-slim\nUSER app\n"),
            ("compose.yml", "services:\n  api:\n    image: app:1.0\n"),
        ]
    )
    assert [d["__docker_file"] for d in merged["dockerfiles"]] == ["backend/Dockerfile"]
    assert [c["__docker_file"] for c in merged["compose_files"]] == ["compose.yml"]


def test_merge_ignores_unrecognised_files() -> None:
    merged = merge_docker_files([("README.md", "# hello"), ("main.tf", "locals {}")])
    assert merged == {"dockerfiles": [], "compose_files": []}


def test_merge_skips_unparseable_files_without_dropping_the_rest() -> None:
    # One bad file must not abort a whole target's scan — the same contract as
    # hcl_parser.merge_terraform_configs.
    merged = merge_docker_files(
        [
            ("compose.yml", "services: [unclosed\n"),
            ("Dockerfile", "# only a comment\n"),
            ("good/Dockerfile", "FROM python:3.12-slim\n"),
        ]
    )
    assert merged["compose_files"] == []
    assert [d["__docker_file"] for d in merged["dockerfiles"]] == ["good/Dockerfile"]


def test_merged_document_is_json_serialisable() -> None:
    # It goes to OPA as an HTTP request body, so this is a hard requirement.
    merged = merge_docker_files(
        [
            ("Dockerfile", "FROM python:3.12\nRUN <<EOF\necho hi\nEOF\n"),
            ("compose.yml", "services:\n  api:\n    image: app:1.0\n    scale: 2\n"),
        ]
    )
    json.dumps(merged)


def test_merge_keeps_every_file_of_the_same_kind() -> None:
    merged = merge_docker_files(
        [
            ("compose.yml", "services:\n  api:\n    image: app:1.0\n"),
            (
                "compose.override.yml",
                "services:\n  api:\n    ports:\n      - '80:80'\n",
            ),
        ]
    )
    # Compose's runtime merge is deliberately not modelled: both files are
    # evaluated as they appear on disk. See merge.py's module docstring.
    assert len(merged["compose_files"]) == 2


def test_empty_input_produces_an_empty_document() -> None:
    assert merge_docker_files([]) == {"dockerfiles": [], "compose_files": []}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("compose.override.yml", True),
        ("compose.override.yaml", True),
        ("docker-compose.override.yml", True),
        ("deploy/compose.override.yml", True),
        ("compose.yml", False),
        # Passed explicitly with -f and may be a complete config, so it is
        # graded as one.
        ("compose.prod.yml", False),
        ("Dockerfile", False),
    ],
)
def test_is_override_file(path: str, expected: bool) -> None:
    assert is_override_file(path) is expected


def test_merge_flags_override_documents() -> None:
    # Absence-based rules read this to decide whether a missing setting means
    # anything; a fragment inherits from the base file.
    merged = merge_docker_files(
        [
            ("compose.yml", "services:\n  api:\n    image: app:1.0\n"),
            (
                "compose.override.yml",
                "services:\n  api:\n    ports:\n      - '80:80'\n",
            ),
        ]
    )
    by_path = {c["__docker_file"]: c for c in merged["compose_files"]}
    assert by_path["compose.yml"]["is_override"] is False
    assert by_path["compose.override.yml"]["is_override"] is True
