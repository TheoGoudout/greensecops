from app.services.terraform.hcl_parser import (
    derive_module_path,
    merge_terraform_configs,
    parse_terraform_content,
)


def test_parse_terraform_content_parses_hcl() -> None:
    raw = """
    resource "aws_s3_bucket" "data" {
      bucket = "my-bucket"
    }
    """
    result = parse_terraform_content("main.tf", raw)
    assert result is not None
    assert result["resource"][0]["aws_s3_bucket"]["data"]["bucket"] == "my-bucket"


def test_parse_terraform_content_preserves_source_line_span() -> None:
    # with_meta=True stamps 1-based start/end lines on every block's attrs dict
    # so a rule can report the exact source span of a violation (spec #3).
    raw = 'resource "aws_s3_bucket" "data" {\n  acl = "public-read"\n}\n'
    result = parse_terraform_content("main.tf", raw)
    assert result is not None
    attrs = result["resource"][0]["aws_s3_bucket"]["data"]
    assert attrs["__start_line__"] == 1
    assert attrs["__end_line__"] == 3


def test_parse_terraform_content_parses_tf_json() -> None:
    raw = '{"resource": {"aws_s3_bucket": {"data": {"bucket": "my-bucket"}}}}'
    result = parse_terraform_content("main.tf.json", raw)
    assert result == {"resource": {"aws_s3_bucket": {"data": {"bucket": "my-bucket"}}}}


def test_parse_terraform_content_returns_none_on_invalid_hcl() -> None:
    result = parse_terraform_content("main.tf", "resource this is not valid !!!")
    assert result is None


def test_parse_terraform_content_returns_none_on_invalid_json() -> None:
    result = parse_terraform_content("main.tf.json", "{not valid json")
    assert result is None


def test_merge_terraform_configs_concatenates_same_block_type_across_files() -> None:
    files = [
        ("main.tf", 'resource "aws_s3_bucket" "data" { bucket = "b1" }'),
        ("network.tf", 'resource "aws_security_group" "web" { name = "sg1" }'),
    ]
    merged = merge_terraform_configs(files)
    assert len(merged["resource"]) == 2


def test_merge_terraform_configs_tags_each_block_with_its_source_file() -> None:
    files = [
        ("main.tf", 'resource "aws_s3_bucket" "data" { bucket = "b1" }'),
        ("network.tf", 'resource "aws_security_group" "web" { name = "sg1" }'),
    ]
    merged = merge_terraform_configs(files)
    tagged_files = {
        block["aws_s3_bucket"]["data"].get("__tf_file")
        for block in merged["resource"]
        if "aws_s3_bucket" in block
    }
    assert tagged_files == {"main.tf"}
    tagged_files_sg = {
        block["aws_security_group"]["web"].get("__tf_file")
        for block in merged["resource"]
        if "aws_security_group" in block
    }
    assert tagged_files_sg == {"network.tf"}


def test_merge_terraform_configs_tags_one_level_blocks_like_variable() -> None:
    # variable/output/locals/module/provider nest one level shallower than
    # resource/data ({name: attrs}, not {type: {name: attrs}}) — this is a
    # regression test for a bug where _tag_source_file assumed the
    # resource/data shape universally and silently left these untagged.
    files = [
        ("vars.tf", 'variable "region" { type = string }'),
    ]
    merged = merge_terraform_configs(files)
    assert merged["variable"][0]["region"]["__tf_file"] == "vars.tf"


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
    files = [
        ("main.tf", 'resource "aws_s3_bucket" "data" { bucket = "b1" }'),
        ("broken.tf", "resource this is not valid !!!"),
    ]
    merged = merge_terraform_configs(files)
    assert len(merged["resource"]) == 1


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
