"""Tests for Compose's merge semantics.

The asymmetry between appended and replaced sequences is the whole point of
this module — getting it backwards is how a merge produces confidently wrong
answers — so most of what follows pins one field's merge behaviour at a time.
"""

from typing import Any

import pytest

from app.services.docker.compose_merge import effective_compose_documents


def _doc(path: str, services: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "__docker_file": path,
        "is_override": ".override." in path,
        "services": services,
        **extra,
    }


def _merged(base_services: dict[str, Any], override_services: dict[str, Any]) -> Any:
    effective = effective_compose_documents(
        [
            _doc("compose.yml", base_services),
            _doc("compose.override.yml", override_services),
        ]
    )
    assert len(effective) == 1
    return effective[0]


def test_a_file_without_an_override_passes_through_unchanged() -> None:
    document = _doc("compose.yml", {"api": {"image": "app:1.0"}})
    assert effective_compose_documents([document]) == [document]


def test_the_pair_collapses_to_one_document_named_for_the_base() -> None:
    merged = _merged({"api": {"image": "app:1.0"}}, {"api": {"scale": 2}})
    assert merged["__docker_file"] == "compose.yml"
    assert merged["__compose_files"] == ["compose.yml", "compose.override.yml"]
    # The merged document is a complete configuration, so absence in it means
    # something — which is exactly what `is_override: False` tells the rules.
    assert merged["is_override"] is False


def test_a_scalar_in_the_override_replaces_the_base() -> None:
    merged = _merged(
        {"api": {"image": "app:1.0", "restart": "no"}},
        {"api": {"restart": "unless-stopped"}},
    )
    assert merged["services"]["api"]["restart"] == "unless-stopped"
    assert merged["services"]["api"]["image"] == "app:1.0"


def test_a_mapping_is_merged_key_by_key() -> None:
    merged = _merged(
        {"api": {"environment": {"LOG_LEVEL": "info", "PORT": "8000"}}},
        {"api": {"environment": {"LOG_LEVEL": "debug", "DEBUG": "1"}}},
    )
    assert merged["services"]["api"]["environment"] == {
        "LOG_LEVEL": "debug",
        "PORT": "8000",
        "DEBUG": "1",
    }


def test_a_nested_mapping_is_merged_rather_than_replaced() -> None:
    # deploy.resources.limits is three levels down and Compose still merges
    # each level, so an override raising the memory limit must not drop the
    # base's cpu limit.
    merged = _merged(
        {
            "api": {
                "deploy": {"resources": {"limits": {"cpus": "0.5", "memory": "256M"}}}
            }
        },
        {"api": {"deploy": {"resources": {"limits": {"memory": "512M"}}}}},
    )
    assert merged["services"]["api"]["deploy"]["resources"]["limits"] == {
        "cpus": "0.5",
        "memory": "512M",
    }


@pytest.mark.parametrize(
    "key",
    [
        "ports",
        "volumes",
        "expose",
        "dns",
        "cap_add",
        "cap_drop",
        "security_opt",
        "tmpfs",
    ],
)
def test_these_sequences_append(key: str) -> None:
    merged = _merged({"api": {key: ["base"]}}, {"api": {key: ["extra"]}})
    assert merged["services"]["api"][key] == ["base", "extra"]


@pytest.mark.parametrize("key", ["command", "entrypoint", "env_file"])
def test_these_sequences_replace(key: str) -> None:
    # You cannot run two commands, so appending here would describe something
    # Compose never does.
    merged = _merged({"api": {key: ["base"]}}, {"api": {key: ["override"]}})
    assert merged["services"]["api"][key] == ["override"]


def test_a_healthcheck_is_replaced_wholesale() -> None:
    # It is a mapping, but a half-merged probe — one file's test with another's
    # interval — is not a configuration either file describes.
    merged = _merged(
        {"db": {"healthcheck": {"test": ["CMD", "pg_isready"], "retries": 10}}},
        {"db": {"healthcheck": {"test": ["CMD", "true"]}}},
    )
    assert merged["services"]["db"]["healthcheck"] == {"test": ["CMD", "true"]}


def test_an_appended_sequence_does_not_duplicate_a_restated_entry() -> None:
    # Restating a port in the override is how people make it explicit, not a
    # request for two of them.
    merged = _merged(
        {"api": {"ports": ["80:80", "443:443"]}},
        {"api": {"ports": ["80:80", "8080:8080"]}},
    )
    assert merged["services"]["api"]["ports"] == ["80:80", "443:443", "8080:8080"]


def test_a_service_only_the_override_declares_is_carried_over() -> None:
    merged = _merged({"api": {"image": "app:1.0"}}, {"debug": {"image": "busybox"}})
    assert set(merged["services"]) == {"api", "debug"}
    assert merged["services"]["debug"] == {
        "image": "busybox",
        "__docker_file": "compose.override.yml",
    }


def test_the_base_line_span_survives_the_merge() -> None:
    # A finding on the merged service should point at the file a reader would
    # open to see it defined, which is the base.
    merged = _merged(
        {"api": {"image": "app:1.0", "__start_line__": 2, "__end_line__": 5}},
        {"api": {"scale": 2, "__start_line__": 40, "__end_line__": 41}},
    )
    assert merged["services"]["api"]["__start_line__"] == 2
    assert merged["services"]["api"]["__end_line__"] == 5
    assert merged["services"]["api"]["__docker_file"] == "compose.yml"


def test_a_service_only_the_override_declares_keeps_the_override_as_its_source() -> (
    None
):
    # The merged document is named for the base, but this service is not in the
    # base at all — citing it there would send a reader to a file the service
    # does not appear in, at a line number taken from a different file.
    merged = _merged(
        {"api": {"image": "app:1.0", "__start_line__": 2, "__end_line__": 3}},
        {"debugger": {"image": "busybox", "__start_line__": 12, "__end_line__": 14}},
    )
    assert merged["services"]["debugger"]["__docker_file"] == "compose.override.yml"
    assert merged["services"]["debugger"]["__start_line__"] == 12
    assert merged["services"]["api"]["__docker_file"] == "compose.yml"


def test_the_override_is_not_returned_alongside_the_merge() -> None:
    # Returning it too would double-report every absence in the pair.
    effective = effective_compose_documents(
        [
            _doc("compose.yml", {"api": {"image": "app:1.0"}}),
            _doc("compose.override.yml", {"api": {"scale": 2}}),
        ]
    )
    assert [d["__docker_file"] for d in effective] == ["compose.yml"]


def test_pairing_survives_the_override_being_listed_first() -> None:
    # A GitHub directory listing has no defined order, and alphabetically the
    # override sorts *before* the base — the opposite of what merging needs.
    effective = effective_compose_documents(
        [
            _doc("compose.override.yml", {"api": {"restart": "always"}}),
            _doc("compose.yml", {"api": {"image": "app:1.0", "restart": "no"}}),
        ]
    )
    assert len(effective) == 1
    assert effective[0]["services"]["api"] == {
        "image": "app:1.0",
        "restart": "always",
        "__docker_file": "compose.yml",
    }


def test_files_are_paired_within_their_own_directory() -> None:
    effective = effective_compose_documents(
        [
            _doc("compose.yml", {"api": {"image": "root:1.0"}}),
            _doc("deploy/compose.yml", {"api": {"image": "deploy:1.0"}}),
            _doc("deploy/compose.override.yml", {"api": {"scale": 3}}),
        ]
    )
    by_path = {d["__docker_file"]: d for d in effective}
    assert set(by_path) == {"compose.yml", "deploy/compose.yml"}
    # The unpaired file passes through untouched, so its services carry no
    # source key and the rules fall back to the document's.
    assert by_path["compose.yml"]["services"]["api"] == {"image": "root:1.0"}
    assert by_path["deploy/compose.yml"]["services"]["api"] == {
        "image": "deploy:1.0",
        "scale": 3,
        "__docker_file": "deploy/compose.yml",
    }


def test_docker_compose_named_files_pair_too() -> None:
    effective = effective_compose_documents(
        [
            _doc("docker-compose.yml", {"api": {"image": "app:1.0"}}),
            _doc("docker-compose.override.yml", {"api": {"scale": 2}}),
        ]
    )
    assert len(effective) == 1
    assert effective[0]["services"]["api"]["scale"] == 2


def test_an_override_with_no_base_contributes_nothing() -> None:
    # Absence in a fragment says nothing, and on its own it is not a
    # configuration — so it yields no effective document rather than being
    # graded as one.
    assert (
        effective_compose_documents([_doc("compose.override.yml", {"api": {}})]) == []
    )


def test_a_yaml_extension_override_pairs_with_its_yaml_base() -> None:
    effective = effective_compose_documents(
        [
            _doc("compose.yaml", {"api": {"image": "app:1.0"}}),
            _doc("compose.override.yaml", {"api": {"scale": 2}}),
        ]
    )
    assert len(effective) == 1
    assert effective[0]["__docker_file"] == "compose.yaml"


def test_top_level_keys_outside_services_merge_too() -> None:
    effective = effective_compose_documents(
        [
            _doc("compose.yml", {}, volumes={"data": None}, networks={"front": None}),
            _doc("compose.override.yml", {}, volumes={"cache": None}),
        ]
    )
    assert effective[0]["volumes"] == {"data": None, "cache": None}
    assert effective[0]["networks"] == {"front": None}


def test_a_null_service_in_the_base_is_replaced_by_the_override_definition() -> None:
    # `api:` with nothing under it parses as None; the override is then the
    # only definition there is.
    merged = _merged({"api": None}, {"api": {"image": "app:1.0"}})
    assert merged["services"]["api"] == {
        "image": "app:1.0",
        "__docker_file": "compose.override.yml",
    }


def test_a_null_service_in_the_override_does_not_erase_the_base() -> None:
    merged = _merged({"api": {"image": "app:1.0"}}, {"api": None})
    assert merged["services"]["api"] == {
        "image": "app:1.0",
        "__docker_file": "compose.yml",
    }


def test_a_non_dict_document_is_ignored() -> None:
    # parse_compose_content only ever returns a mapping or None, but the list
    # arrives from a caller and this must not raise.
    assert effective_compose_documents(["not a document"]) == []  # type: ignore[list-item]
