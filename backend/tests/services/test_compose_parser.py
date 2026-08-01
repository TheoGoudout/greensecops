import json

from app.services.docker.compose_parser import parse_compose_content


def test_parses_services_and_tags_the_source_file() -> None:
    raw = "services:\n  api:\n    image: app:1.0\n"
    parsed = parse_compose_content("compose.yml", raw)
    assert parsed is not None
    assert parsed["__docker_file"] == "compose.yml"
    assert parsed["services"]["api"]["image"] == "app:1.0"


def test_stamps_each_service_with_its_source_span() -> None:
    # __start_line__ is the line of the service's own key, so a finding points
    # at `api:` rather than at wherever the offending value happens to sit.
    raw = (
        "services:\n"
        "  api:\n"
        "    image: app:1.0\n"
        "    privileged: true\n"
        "  worker:\n"
        "    image: worker:1.0\n"
    )
    parsed = parse_compose_content("compose.yml", raw)
    assert parsed is not None
    assert parsed["services"]["api"]["__start_line__"] == 2
    assert parsed["services"]["api"]["__end_line__"] == 4
    assert parsed["services"]["worker"]["__start_line__"] == 5
    assert parsed["services"]["worker"]["__end_line__"] == 6


def test_span_covers_nested_blocks() -> None:
    raw = (
        "services:\n"
        "  api:\n"
        "    build:\n"
        "      context: .\n"
        "      dockerfile: backend/Dockerfile\n"
        "    ports:\n"
        '      - "8080:8080"\n'
    )
    parsed = parse_compose_content("compose.yml", raw)
    assert parsed is not None
    assert parsed["services"]["api"]["__start_line__"] == 2
    assert parsed["services"]["api"]["__end_line__"] == 7


def test_round_trip_types_are_converted_to_plain_json() -> None:
    # The document is POSTed to OPA as JSON, so ruamel's round-trip node types
    # must not survive into the result.
    raw = (
        "services:\n"
        "  api:\n"
        "    image: app:1.0\n"
        "    privileged: true\n"
        "    scale: 3\n"
        "    cpus: 1.5\n"
        "    environment:\n"
        "      - FOO=bar\n"
    )
    parsed = parse_compose_content("compose.yml", raw)
    assert parsed is not None
    api = parsed["services"]["api"]
    assert api["privileged"] is True
    assert api["scale"] == 3
    assert api["cpus"] == 1.5
    assert api["environment"] == ["FOO=bar"]
    # Serialises without a custom encoder.
    json.dumps(parsed)


def test_yaml_12_core_schema_keeps_no_and_on_as_strings() -> None:
    # `restart: no` must stay the string Compose expects, not become False the
    # way a YAML 1.1 loader would have it — the same trap documented in
    # opa.evaluator.parse_workflow_yaml for the workflow `on:` key.
    raw = "services:\n  api:\n    image: app:1.0\n    restart: no\n"
    parsed = parse_compose_content("compose.yml", raw)
    assert parsed is not None
    assert parsed["services"]["api"]["restart"] == "no"


def test_service_with_an_empty_body_is_not_stamped() -> None:
    raw = "services:\n  api:\n"
    parsed = parse_compose_content("compose.yml", raw)
    assert parsed is not None
    assert parsed["services"]["api"] is None


def test_top_level_keys_other_than_services_are_preserved() -> None:
    raw = 'version: "3.8"\nservices:\n  api:\n    image: app:1.0\nvolumes:\n  data:\n'
    parsed = parse_compose_content("compose.yml", raw)
    assert parsed is not None
    assert parsed["version"] == "3.8"
    assert "data" in parsed["volumes"]


def test_returns_none_on_malformed_yaml() -> None:
    assert parse_compose_content("compose.yml", "services: [unclosed\n") is None


def test_returns_none_when_document_is_not_a_mapping() -> None:
    assert parse_compose_content("compose.yml", "- just\n- a\n- list\n") is None


def test_file_without_services_still_parses() -> None:
    parsed = parse_compose_content("compose.yml", "volumes:\n  data:\n")
    assert parsed is not None
    assert parsed["__docker_file"] == "compose.yml"


def test_non_json_scalars_are_stringified() -> None:
    # YAML types an unquoted date natively, and datetime.date is not JSON
    # serialisable — it must not reach the OPA request body as an object.
    raw = "services:\n  api:\n    image: app:1.0\n    x-released: 2026-07-31\n"
    parsed = parse_compose_content("compose.yml", raw)
    assert parsed is not None
    assert parsed["services"]["api"]["x-released"] == "2026-07-31"
    json.dumps(parsed)
