"""Unit tests for the HCL parser, anchored in real-world Terraform.

The modules under ``tests/fixtures/terraform/`` are vendored verbatim from
public repositories (see the README there), so these tests exercise the parser
against configuration people actually wrote — heredocs, ``dynamic`` blocks,
``for_each`` comprehensions, interpolation, repeated nested blocks — rather than
snippets shaped to fit the assertion. Synthetic input survives only where the
test needs input that is deliberately malformed.
"""

import json
from pathlib import Path

from app.services.terraform.hcl_parser import (
    derive_module_path,
    merge_terraform_configs,
    parse_terraform_content,
)

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "terraform"

# bridgecrewio/terragoat's AWS estate — deliberately insecure, and written the
# way real Terraform is written.
_TERRAGOAT = _FIXTURES / "terragoat_aws"
# terraform-aws-modules/terraform-aws-security-group — a hardened registry
# module, all `for_each`/`dynamic`/`try()`, with fully described variables.
_SECURITY_GROUP = _FIXTURES / "terraform_aws_security_group"


def _load(path: Path) -> str:
    return path.read_text()


def _root(case_dir: Path) -> list[tuple[str, str]]:
    """A whole vendored root module as ``(path, content)`` pairs."""
    return [
        (p.name, p.read_text())
        for p in sorted(case_dir.iterdir())
        if p.name.endswith((".tf", ".tf.json"))
    ]


def test_parse_terraform_content_parses_hcl() -> None:
    result = parse_terraform_content("s3.tf", _load(_TERRAGOAT / "s3.tf"))
    assert result is not None
    buckets = result["resource"][0]["aws_s3_bucket"]
    assert buckets["data"]["bucket"] == "${local.resource_prefix.value}-data"


def test_parse_terraform_content_parses_a_heredoc_and_nested_blocks() -> None:
    # ec2.tf's aws_instance carries a shell heredoc in user_data and the
    # security group repeats `ingress` twice — both are shapes a hand-written
    # one-liner fixture never produces.
    result = parse_terraform_content("ec2.tf", _load(_TERRAGOAT / "ec2.tf"))
    assert result is not None
    resources = {
        name: attrs
        for block in result["resource"]
        for named in block.values()
        for name, attrs in named.items()
    }
    assert "AWS_ACCESS_KEY_ID" in resources["web_host"]["user_data"]
    assert len(resources["web-node"]["ingress"]) == 2


def test_parse_terraform_content_preserves_source_line_span() -> None:
    # with_meta=True stamps 1-based start/end lines on every block's attrs dict
    # so a rule can report the exact source span of a violation (spec #3). The
    # unencrypted EBS volume is the 34th-51st line of the real file.
    raw = _load(_TERRAGOAT / "ec2.tf")
    result = parse_terraform_content("ec2.tf", raw)
    assert result is not None
    volume = next(
        block["aws_ebs_volume"]["web_host_storage"]
        for block in result["resource"]
        if "aws_ebs_volume" in block
    )
    start, end = volume["__start_line__"], volume["__end_line__"]
    lines = raw.splitlines()
    assert lines[start - 1].startswith('resource "aws_ebs_volume"')
    assert lines[end - 1].strip() == "}"


def test_parse_terraform_content_parses_tf_json() -> None:
    # JSON Terraform is the same document in the other syntax: round-trip a real
    # parsed module through it and the parser must accept it unchanged.
    parsed = parse_terraform_content("s3.tf", _load(_TERRAGOAT / "s3.tf"))
    assert parsed is not None
    result = parse_terraform_content("main.tf.json", json.dumps(parsed))
    assert result == parsed


def test_parse_terraform_content_returns_none_on_invalid_hcl() -> None:
    result = parse_terraform_content("main.tf", "resource this is not valid !!!")
    assert result is None


def test_parse_terraform_content_returns_none_on_invalid_json() -> None:
    result = parse_terraform_content("main.tf.json", "{not valid json")
    assert result is None


def test_merge_terraform_configs_concatenates_same_block_type_across_files() -> None:
    # Terraform treats a directory as one module, so resources declared in
    # separate real files land in a single `resource` list.
    files = _root(_TERRAGOAT)
    per_file = {
        name: len((parse_terraform_content(name, content) or {}).get("resource", []))
        for name, content in files
    }
    contributors = [name for name, count in per_file.items() if count]
    assert len(contributors) >= 3, "fixture no longer spreads resources across files"

    merged = merge_terraform_configs(files)
    assert len(merged["resource"]) == sum(per_file.values())


def test_merge_terraform_configs_tags_each_block_with_its_source_file() -> None:
    merged = merge_terraform_configs(_root(_TERRAGOAT))
    source_of = {
        f"{resource_type}.{name}": attrs["__tf_file"]
        for block in merged["resource"]
        for resource_type, named in block.items()
        for name, attrs in named.items()
    }
    # Each of these really is declared in the file it is tagged with.
    assert source_of["aws_s3_bucket.data"] == "s3.tf"
    assert source_of["aws_security_group.web-node"] == "ec2.tf"
    assert source_of["aws_db_instance.default"] == "db-app.tf"
    assert source_of["aws_lambda_function.analysis_lambda"] == "lambda.tf"


def test_merge_terraform_configs_tags_one_level_blocks_like_variable() -> None:
    # variable/output/locals/module/provider nest one level shallower than
    # resource/data ({name: attrs}, not {type: {name: attrs}}) — this is a
    # regression test for a bug where _tag_source_file assumed the
    # resource/data shape universally and silently left these untagged.
    merged = merge_terraform_configs(_root(_SECURITY_GROUP))
    variables = {
        name: attrs for block in merged["variable"] for name, attrs in block.items()
    }
    assert len(variables) > 1
    assert all(attrs["__tf_file"] == "variables.tf" for attrs in variables.values())


def test_merge_terraform_configs_tags_the_unnamed_terraform_block() -> None:
    # `terraform` is the one block type whose entry *is* the attrs dict rather
    # than a {name: attrs} mapping, so walking into its values stamps nothing —
    # they are a version string and a nested list. Findings about a backend or
    # a provider constraint had no file to point at until it was stamped at the
    # top level.
    files = [
        (
            "versions.tf",
            'terraform {\n  required_version = ">= 1.9"\n'
            '  required_providers {\n    aws = { source = "hashicorp/aws" }\n  }\n}',
        ),
    ]
    merged = merge_terraform_configs(files)
    assert merged["terraform"][0]["__tf_file"] == "versions.tf"


def test_merge_terraform_configs_does_not_invent_a_local_named_tf_file() -> None:
    # `locals` keys are user-chosen names, so stamping that block the way
    # `terraform` is stamped would add a local called __tf_file.
    merged = merge_terraform_configs([("locals.tf", 'locals {\n  env = "prod"\n}')])
    assert "__tf_file" not in merged["locals"][0]


def test_merge_terraform_configs_skips_unparseable_files() -> None:
    good = _root(_TERRAGOAT)
    merged = merge_terraform_configs(
        [*good, ("broken.tf", "resource this is not valid !!!")]
    )
    assert merged == merge_terraform_configs(good)


def test_merge_terraform_configs_empty_input() -> None:
    assert merge_terraform_configs([]) == {}


def test_derive_module_path_root_level_file_is_none() -> None:
    # A file directly in the root (or its root_path prefix) has no module.
    assert derive_module_path("main.tf", "") is None
    assert derive_module_path("main.tf", ".") is None
    assert derive_module_path("infra/prod/main.tf", "infra/prod") is None


def test_derive_module_path_subdirectory_is_relative_dir() -> None:
    assert (
        derive_module_path("infra/prod/modules/storage/main.tf", "infra/prod")
        == "modules/storage"
    )
    # No root_path prefix: the whole directory is the module locator.
    assert derive_module_path("modules/vpc/main.tf", "") == "modules/vpc"


def test_derive_module_path_file_outside_root_falls_back_to_its_dir() -> None:
    # Defensive: file not actually under root_path — use its own parent dir.
    assert derive_module_path("other/main.tf", "infra/prod") == "other"
