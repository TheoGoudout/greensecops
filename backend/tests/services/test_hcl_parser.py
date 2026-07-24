from app.services.terraform.hcl_parser import (
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


def test_merge_terraform_configs_skips_unparseable_files() -> None:
    files = [
        ("main.tf", 'resource "aws_s3_bucket" "data" { bucket = "b1" }'),
        ("broken.tf", "resource this is not valid !!!"),
    ]
    merged = merge_terraform_configs(files)
    assert len(merged["resource"]) == 1


def test_merge_terraform_configs_empty_input() -> None:
    assert merge_terraform_configs([]) == {}
