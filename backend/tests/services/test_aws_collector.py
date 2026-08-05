"""Tests for the AWS resource collector's normalization logic.

Mirrors tests/services/test_app_client.py's approach to the GitHub client:
the AWS SDK boundary (boto3) is mocked the same way PyGithub is there — real
network/AWS calls aren't available in CI, so what's under test is GreenSecOps'
own normalization logic, not boto3 itself.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from app.core.config import settings
from app.services.cloud.aws_collector import (
    CloudCollectionError,
    _assume_role_session,
    _base_sts_client,
    _collect_cloudtrail_trails,
    _collect_cloudwatch_log_groups,
    _collect_ebs_volumes,
    _collect_ecr_repositories,
    _collect_eks_clusters,
    _collect_iam,
    _collect_kms_keys,
    _collect_lambda_functions,
    _collect_load_balancers,
    _collect_rds_instances,
    _collect_s3_buckets,
    _collect_secrets,
    _collect_security_groups,
    _credential_report,
    collect_account_resources,
)


def _client_error(code: str, operation: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, operation)


class TestBaseStsClient:
    @patch("app.services.cloud.aws_collector.boto3")
    def test_uses_explicit_credentials_when_configured(
        self, mock_boto3: MagicMock
    ) -> None:
        with (
            patch.object(settings, "AWS_ACCESS_KEY_ID", "AKIA_BASE"),
            patch.object(settings, "AWS_SECRET_ACCESS_KEY", "base-secret"),
            patch.object(settings, "AWS_DEFAULT_REGION", "eu-west-1"),
        ):
            _base_sts_client()

        mock_boto3.client.assert_called_once_with(
            "sts",
            aws_access_key_id="AKIA_BASE",
            aws_secret_access_key="base-secret",
            region_name="eu-west-1",
        )

    @patch("app.services.cloud.aws_collector.boto3")
    def test_falls_back_to_default_chain_when_unconfigured(
        self, mock_boto3: MagicMock
    ) -> None:
        with (
            patch.object(settings, "AWS_ACCESS_KEY_ID", ""),
            patch.object(settings, "AWS_SECRET_ACCESS_KEY", ""),
            patch.object(settings, "AWS_DEFAULT_REGION", "us-east-1"),
        ):
            _base_sts_client()

        mock_boto3.client.assert_called_once_with("sts", region_name="us-east-1")


class TestAssumeRoleSession:
    @patch("app.services.cloud.aws_collector.boto3")
    def test_success_builds_session_from_temp_credentials(
        self, mock_boto3: MagicMock
    ) -> None:
        mock_sts = MagicMock()
        mock_sts.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "AKIA_TEST",
                "SecretAccessKey": "secret",
                "SessionToken": "token",
            }
        }
        mock_boto3.client.return_value = mock_sts

        _assume_role_session("arn:aws:iam::123:role/x", "ext-id")

        mock_boto3.Session.assert_called_once_with(
            aws_access_key_id="AKIA_TEST",
            aws_secret_access_key="secret",
            aws_session_token="token",
        )

    @patch("app.services.cloud.aws_collector.boto3")
    def test_assume_role_failure_raises_collection_error(
        self, mock_boto3: MagicMock
    ) -> None:
        mock_sts = MagicMock()
        mock_sts.assume_role.side_effect = _client_error("AccessDenied", "AssumeRole")
        mock_boto3.client.return_value = mock_sts

        with pytest.raises(CloudCollectionError):
            _assume_role_session("arn:aws:iam::123:role/x", "ext-id")


class TestCollectS3Buckets:
    def test_normalizes_access_block_encryption_and_versioning(self) -> None:
        session = MagicMock()
        client = MagicMock()
        session.client.return_value = client
        client.list_buckets.return_value = {"Buckets": [{"Name": "my-bucket"}]}
        client.get_public_access_block.return_value = {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": False,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": False,
            }
        }
        client.get_bucket_encryption.return_value = {
            "ServerSideEncryptionConfiguration": {"Rules": [{"foo": "bar"}]}
        }
        client.get_bucket_versioning.return_value = {"Status": "Enabled"}
        client.get_bucket_logging.return_value = {
            "LoggingEnabled": {"TargetBucket": "logs"}
        }
        client.get_bucket_policy.side_effect = _client_error(
            "NoSuchBucketPolicy", "GetBucketPolicy"
        )

        buckets = _collect_s3_buckets(session)

        assert buckets == [
            {
                "name": "my-bucket",
                "block_public_acls": True,
                "block_public_policy": False,
                "ignore_public_acls": True,
                "restrict_public_buckets": False,
                "encrypted": True,
                "kms_key_id": None,
                "versioning_enabled": True,
                "logging_enabled": True,
                "policy_statements": [],
            }
        ]

    def test_reports_the_cmk_when_one_is_configured(self) -> None:
        # A bare `encrypted` boolean cannot distinguish the AWS-managed default
        # from a key whose access the account actually controls.
        session = MagicMock()
        client = MagicMock()
        session.client.return_value = client
        client.list_buckets.return_value = {"Buckets": [{"Name": "my-bucket"}]}
        client.get_bucket_encryption.return_value = {
            "ServerSideEncryptionConfiguration": {
                "Rules": [
                    {
                        "ApplyServerSideEncryptionByDefault": {
                            "SSEAlgorithm": "aws:kms",
                            "KMSMasterKeyID": "arn:aws:kms:eu-west-1:1:key/abc",
                        }
                    }
                ]
            }
        }
        client.get_bucket_policy.side_effect = _client_error(
            "NoSuchBucketPolicy", "GetBucketPolicy"
        )

        buckets = _collect_s3_buckets(session)

        assert buckets[0]["kms_key_id"] == "arn:aws:kms:eu-west-1:1:key/abc"

    def test_normalizes_a_public_bucket_policy(self) -> None:
        # The one route to public that neither the ACL nor the access-block
        # check can see.
        session = MagicMock()
        client = MagicMock()
        session.client.return_value = client
        client.list_buckets.return_value = {"Buckets": [{"Name": "my-bucket"}]}
        client.get_bucket_encryption.side_effect = _client_error(
            "ServerSideEncryptionConfigurationNotFoundError", "GetBucketEncryption"
        )
        client.get_bucket_policy.return_value = {
            "Policy": json.dumps(
                {
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": "*",
                            "Action": "s3:GetObject",
                            "Resource": "arn:aws:s3:::my-bucket/*",
                        }
                    ]
                }
            )
        }

        buckets = _collect_s3_buckets(session)

        assert buckets[0]["policy_statements"] == [
            {
                "effect": "Allow",
                "actions": ["s3:GetObject"],
                "resources": ["arn:aws:s3:::my-bucket/*"],
                "principals": ["*"],
                "has_condition": False,
            }
        ]

    def test_flattens_the_principal_mapping_form(self) -> None:
        session = MagicMock()
        client = MagicMock()
        session.client.return_value = client
        client.list_buckets.return_value = {"Buckets": [{"Name": "b"}]}
        client.get_bucket_policy.return_value = {
            "Policy": json.dumps(
                {
                    "Statement": {
                        "Effect": "Allow",
                        "Principal": {"AWS": ["*"]},
                        "Action": ["s3:*"],
                        "Resource": "*",
                        "Condition": {"StringEquals": {"aws:SourceVpc": "vpc-1"}},
                    }
                }
            )
        }

        buckets = _collect_s3_buckets(session)

        statement = buckets[0]["policy_statements"][0]
        assert statement["principals"] == ["*"]
        # A wide grant that a condition narrows is a different finding from one
        # that nothing narrows.
        assert statement["has_condition"] is True

    def test_missing_access_block_and_encryption_default_to_disabled(self) -> None:
        session = MagicMock()
        client = MagicMock()
        session.client.return_value = client
        client.list_buckets.return_value = {"Buckets": [{"Name": "my-bucket"}]}
        client.get_public_access_block.side_effect = _client_error(
            "NoSuchPublicAccessBlockConfiguration", "GetPublicAccessBlock"
        )
        client.get_bucket_encryption.side_effect = _client_error(
            "ServerSideEncryptionConfigurationNotFoundError", "GetBucketEncryption"
        )
        client.get_bucket_versioning.return_value = {}

        buckets = _collect_s3_buckets(session)

        assert buckets[0]["block_public_acls"] is False
        assert buckets[0]["encrypted"] is False
        assert buckets[0]["versioning_enabled"] is False


class TestCollectSecurityGroups:
    def test_normalizes_ingress_rules_across_regions(self) -> None:
        session = MagicMock()

        def _client(service: str, region_name: str) -> MagicMock:
            client = MagicMock()
            paginator = MagicMock()
            client.get_paginator.return_value = paginator
            paginator.paginate.return_value = [
                {
                    "SecurityGroups": [
                        {
                            "GroupId": f"sg-{region_name}",
                            "GroupName": "web",
                            "IpPermissions": [
                                {
                                    "FromPort": 22,
                                    "ToPort": 22,
                                    "IpProtocol": "tcp",
                                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                                    "Ipv6Ranges": [],
                                }
                            ],
                        }
                    ]
                }
            ]
            return client

        session.client.side_effect = _client

        groups = _collect_security_groups(session, ["us-east-1", "eu-west-1"])

        assert {g["id"] for g in groups} == {"sg-us-east-1", "sg-eu-west-1"}
        assert groups[0]["ingress_rules"] == [
            {
                "from_port": 22,
                "to_port": 22,
                "ip_protocol": "tcp",
                "cidr_blocks": ["0.0.0.0/0"],
            }
        ]

    def test_region_failure_does_not_abort_other_regions(self) -> None:
        session = MagicMock()

        def _client(service: str, region_name: str) -> MagicMock:
            client = MagicMock()
            if region_name == "us-east-1":
                client.get_paginator.side_effect = _client_error(
                    "UnauthorizedOperation", "DescribeSecurityGroups"
                )
                return client
            paginator = MagicMock()
            client.get_paginator.return_value = paginator
            paginator.paginate.return_value = [
                {"SecurityGroups": [{"GroupId": "sg-ok", "IpPermissions": []}]}
            ]
            return client

        session.client.side_effect = _client

        groups = _collect_security_groups(session, ["us-east-1", "eu-west-1"])

        assert [g["id"] for g in groups] == ["sg-ok"]


class TestCollectIam:
    def test_normalizes_users_and_wildcard_policy_statements(self) -> None:
        session = MagicMock()
        client = MagicMock()
        session.client.return_value = client

        users_paginator = MagicMock()
        policies_paginator = MagicMock()

        def _get_paginator(name: str) -> MagicMock:
            return {"list_users": users_paginator, "list_policies": policies_paginator}[
                name
            ]

        client.get_paginator.side_effect = _get_paginator
        users_paginator.paginate.return_value = [
            {"Users": [{"UserName": "alice"}, {"UserName": "bob"}]}
        ]
        policies_paginator.paginate.return_value = [
            {
                "Policies": [
                    {
                        "PolicyName": "admin",
                        "Arn": "arn:aws:iam::1:policy/admin",
                        "DefaultVersionId": "v1",
                    }
                ]
            }
        ]

        def _list_mfa_devices(UserName: str) -> dict:  # noqa: N803 - boto3 kwarg name
            return {"MFADevices": [{}]} if UserName == "alice" else {"MFADevices": []}

        client.list_mfa_devices.side_effect = _list_mfa_devices
        client.get_policy_version.return_value = {
            "PolicyVersion": {
                "Document": {
                    "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]
                }
            }
        }

        users, policies = _collect_iam(session)

        # The credential report is unavailable in this fixture, so every field
        # it supplies is None — "not measured", which a rule must not read as
        # "measured and fine".
        assert users == [
            {
                "name": "alice",
                "mfa_enabled": True,
                "console_access": None,
                "access_key_age_days": None,
                "access_key_unused_days": None,
            },
            {
                "name": "bob",
                "mfa_enabled": False,
                "console_access": None,
                "access_key_age_days": None,
                "access_key_unused_days": None,
            },
        ]
        assert policies == [
            {
                "name": "admin",
                "arn": "arn:aws:iam::1:policy/admin",
                "statements": [
                    {
                        "effect": "Allow",
                        "actions": ["*"],
                        "resources": ["*"],
                        # An identity policy has no Principal — the field
                        # exists because the same normalizer reads resource
                        # policies, where it is what makes "public" detectable.
                        "principals": [],
                        "has_condition": False,
                    }
                ],
            }
        ]

    def test_url_encoded_policy_document_string_is_decoded(self) -> None:
        session = MagicMock()
        client = MagicMock()
        session.client.return_value = client

        users_paginator = MagicMock()
        policies_paginator = MagicMock()
        client.get_paginator.side_effect = lambda name: {
            "list_users": users_paginator,
            "list_policies": policies_paginator,
        }[name]
        users_paginator.paginate.return_value = [{"Users": []}]
        policies_paginator.paginate.return_value = [
            {
                "Policies": [
                    {
                        "PolicyName": "scoped",
                        "Arn": "arn:aws:iam::1:policy/scoped",
                        "DefaultVersionId": "v1",
                    }
                ]
            }
        ]
        client.get_policy_version.return_value = {
            "PolicyVersion": {
                "Document": "%7B%22Statement%22%3A%5B%7B%22Effect%22%3A%22Allow%22%2C%22Action%22%3A%22s3%3AGetObject%22%2C%22Resource%22%3A%22%2A%22%7D%5D%7D"
            }
        }

        _, policies = _collect_iam(session)

        assert policies[0]["statements"] == [
            {
                "effect": "Allow",
                "actions": ["s3:GetObject"],
                "resources": ["*"],
                "principals": [],
                "has_condition": False,
            }
        ]


class TestCollectRdsAndEbs:
    def test_rds_instances_normalized(self) -> None:
        session = MagicMock()
        client = MagicMock()
        session.client.return_value = client
        paginator = MagicMock()
        client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [
            {
                "DBInstances": [
                    {
                        "DBInstanceIdentifier": "db1",
                        "PubliclyAccessible": True,
                        "StorageEncrypted": False,
                    }
                ]
            }
        ]

        instances = _collect_rds_instances(session, ["us-east-1"])

        assert instances == [
            {
                "id": "db1",
                "region": "us-east-1",
                "engine": "",
                "publicly_accessible": True,
                "storage_encrypted": False,
                "kms_key_id": None,
                "backup_retention_days": 0,
                "multi_az": False,
                "auto_minor_version_upgrade": False,
                "deletion_protection": False,
            }
        ]

    def test_ebs_volumes_normalized(self) -> None:
        session = MagicMock()
        client = MagicMock()
        session.client.return_value = client
        paginator = MagicMock()
        client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [
            {
                "Volumes": [
                    {
                        "VolumeId": "vol-1",
                        "Encrypted": False,
                        "Attachments": [],
                    }
                ]
            }
        ]

        volumes = _collect_ebs_volumes(session, ["us-east-1"])

        assert volumes == [
            {
                "id": "vol-1",
                "region": "us-east-1",
                "encrypted": False,
                "kms_key_id": None,
                "volume_type": "",
                "size_gb": 0,
                "attached": False,
            }
        ]


class TestCollectAccountResources:
    @patch("app.services.cloud.aws_collector._assume_role_session")
    def test_returns_all_expected_keys(self, mock_assume: MagicMock) -> None:
        session = MagicMock()
        client = MagicMock()
        session.client.return_value = client
        client.list_buckets.return_value = {"Buckets": []}
        paginator = MagicMock()
        client.get_paginator.return_value = paginator
        paginator.paginate.return_value = []
        client.describe_trails.return_value = {"trailList": []}
        mock_assume.return_value = session

        resources = collect_account_resources(
            "arn:aws:iam::123:role/x", "ext-id", ["us-east-1"]
        )

        assert set(resources.keys()) == {
            "s3_buckets",
            "security_groups",
            "iam_users",
            "iam_policies",
            "rds_instances",
            "ebs_volumes",
            "lambda_functions",
            "cloudtrail_trails",
            "cloudwatch_log_groups",
            "eks_clusters",
            "ecr_repositories",
            "load_balancers",
            "secrets",
            "kms_keys",
        }

    @patch("app.services.cloud.aws_collector._assume_role_session")
    def test_every_value_is_a_list(self, mock_assume: MagicMock) -> None:
        # cloud_scan sums len() over these to report a resource count, so a
        # scalar value would raise there rather than here.
        session = MagicMock()
        client = MagicMock()
        session.client.return_value = client
        client.list_buckets.return_value = {"Buckets": []}
        paginator = MagicMock()
        client.get_paginator.return_value = paginator
        paginator.paginate.return_value = []
        client.describe_trails.return_value = {"trailList": []}
        mock_assume.return_value = session

        resources = collect_account_resources(
            "arn:aws:iam::123:role/x", "ext-id", ["us-east-1"]
        )

        assert all(isinstance(v, list) for v in resources.values())
        assert sum(len(v) for v in resources.values()) == 0

    @patch("app.services.cloud.aws_collector._assume_role_session")
    def test_one_collector_raising_does_not_abort_the_scan(
        self, mock_assume: MagicMock
    ) -> None:
        # The collectors already swallow API errors; this covers a bug in
        # normalization, which must cost one resource type rather than the
        # whole account.
        session = MagicMock()
        client = MagicMock()
        session.client.return_value = client
        client.list_buckets.side_effect = RuntimeError("boom")
        paginator = MagicMock()
        client.get_paginator.return_value = paginator
        paginator.paginate.return_value = []
        client.describe_trails.return_value = {"trailList": []}
        mock_assume.return_value = session

        resources = collect_account_resources(
            "arn:aws:iam::123:role/x", "ext-id", ["us-east-1"]
        )

        assert resources["s3_buckets"] == []
        assert "ebs_volumes" in resources


# ─── Collectors added with the signal expansion ──────────────────────────────


def _paginated(session: MagicMock, pages: list[dict[str, Any]]) -> MagicMock:
    client = MagicMock()
    session.client.return_value = client
    paginator = MagicMock()
    client.get_paginator.return_value = paginator
    paginator.paginate.return_value = pages
    return client


class TestCollectLambdaFunctions:
    def test_reports_environment_names_but_never_values(self) -> None:
        # The values are exactly the secrets a rule wants to know were put
        # here, so shipping them would recreate the problem being reported.
        session = MagicMock()
        client = _paginated(
            session,
            [
                {
                    "Functions": [
                        {
                            "FunctionName": "api",
                            "Runtime": "python3.13",
                            "Environment": {
                                "Variables": {
                                    "DB_PASSWORD": "hunter2",
                                    "LOG_LEVEL": "info",
                                }
                            },
                            "VpcConfig": {"SubnetIds": ["subnet-1"]},
                            "TracingConfig": {"Mode": "Active"},
                        }
                    ]
                }
            ],
        )
        client.get_function_url_config.side_effect = _client_error(
            "ResourceNotFoundException", "GetFunctionUrlConfig"
        )

        functions = _collect_lambda_functions(session, ["eu-west-1"])

        assert functions[0]["environment_names"] == ["DB_PASSWORD", "LOG_LEVEL"]
        assert "hunter2" not in json.dumps(functions)
        assert functions[0]["vpc_configured"] is True
        assert functions[0]["tracing_enabled"] is True
        assert functions[0]["public_url"] is False

    def test_a_function_url_with_no_auth_is_flagged(self) -> None:
        session = MagicMock()
        client = _paginated(
            session, [{"Functions": [{"FunctionName": "api", "Runtime": "python3.13"}]}]
        )
        client.get_function_url_config.return_value = {"AuthType": "NONE"}

        functions = _collect_lambda_functions(session, ["eu-west-1"])

        assert functions[0]["public_url"] is True


class TestCollectCloudTrail:
    def test_reports_multi_region_and_validation(self) -> None:
        session = MagicMock()
        client = MagicMock()
        session.client.return_value = client
        client.describe_trails.return_value = {
            "trailList": [
                {
                    "Name": "org-audit",
                    "TrailARN": "arn:aws:cloudtrail:eu-west-1:1:trail/org-audit",
                    "HomeRegion": "eu-west-1",
                    "IsMultiRegionTrail": True,
                    "LogFileValidationEnabled": False,
                }
            ]
        }
        client.get_trail_status.return_value = {"IsLogging": True}

        trails = _collect_cloudtrail_trails(session, ["eu-west-1"])

        assert trails[0]["is_multi_region"] is True
        assert trails[0]["log_file_validation_enabled"] is False
        assert trails[0]["is_logging"] is True

    def test_no_regions_configured_returns_nothing(self) -> None:
        assert _collect_cloudtrail_trails(MagicMock(), []) == []


class TestCredentialReport:
    def test_parses_key_age_and_last_use(self) -> None:
        client = MagicMock()
        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        recent = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        client.get_credential_report.return_value = {
            "Content": (
                "user,password_enabled,access_key_1_last_rotated,"
                "access_key_1_last_used_date,access_key_2_last_rotated,"
                "access_key_2_last_used_date\n"
                f"alice,true,{old},{recent},N/A,N/A\n"
                "<root_account>,true,N/A,N/A,N/A,N/A\n"
            ).encode()
        }

        report = _credential_report(client)

        assert report["alice"]["console_access"] is True
        assert report["alice"]["access_key_age_days"] == 400
        assert report["alice"]["access_key_unused_days"] == 5
        # The root account is not an IAM user and has no `list_users` entry to
        # merge onto.
        assert "<root_account>" not in report

    def test_unavailable_report_degrades_to_nothing(self) -> None:
        # The report is generated asynchronously, so a first call can fail
        # while it builds. That must cost the fields, not the scan.
        client = MagicMock()
        client.generate_credential_report.side_effect = _client_error(
            "AccessDenied", "GenerateCredentialReport"
        )
        assert _credential_report(client) == {}

    def test_placeholder_values_are_read_as_unknown(self) -> None:
        client = MagicMock()
        client.get_credential_report.return_value = {
            "Content": (
                b"user,password_enabled,access_key_1_last_rotated,"
                b"access_key_1_last_used_date\n"
                b"bob,false,N/A,no_information\n"
            )
        }

        report = _credential_report(client)

        assert report["bob"]["access_key_age_days"] is None
        assert report["bob"]["access_key_unused_days"] is None


class TestCollectCloudWatchLogGroups:
    def test_absent_retention_is_reported_as_none(self) -> None:
        # Absent means "never expire" — the default, and the finding.
        session = MagicMock()
        _paginated(session, [{"logGroups": [{"logGroupName": "/aws/lambda/api"}]}])

        groups = _collect_cloudwatch_log_groups(session, ["eu-west-1"])

        assert groups == [
            {
                "name": "/aws/lambda/api",
                "region": "eu-west-1",
                "retention_days": None,
                "kms_key_id": None,
                "stored_bytes": 0,
            }
        ]


class TestCollectEksClusters:
    def test_normalizes_endpoint_access_and_logging(self) -> None:
        session = MagicMock()
        client = _paginated(session, [{"clusters": ["prod"]}])
        client.describe_cluster.return_value = {
            "cluster": {
                "version": "1.31",
                "resourcesVpcConfig": {
                    "endpointPublicAccess": True,
                    "endpointPrivateAccess": False,
                    "publicAccessCidrs": ["0.0.0.0/0"],
                },
                "logging": {
                    "clusterLogging": [
                        {"enabled": True, "types": ["audit"]},
                        {"enabled": False, "types": ["scheduler"]},
                    ]
                },
                "encryptionConfig": [{"provider": {"keyArn": "arn:aws:kms:::key/a"}}],
            }
        }

        clusters = _collect_eks_clusters(session, ["eu-west-1"])

        assert clusters[0]["endpoint_public_access"] is True
        assert clusters[0]["public_access_cidrs"] == ["0.0.0.0/0"]
        # Only the enabled log types — a disabled one is not evidence of
        # anything being recorded.
        assert clusters[0]["enabled_log_types"] == ["audit"]
        assert clusters[0]["secrets_encrypted"] is True

    def test_a_cluster_that_cannot_be_described_is_skipped(self) -> None:
        session = MagicMock()
        client = _paginated(session, [{"clusters": ["prod"]}])
        client.describe_cluster.side_effect = _client_error(
            "AccessDeniedException", "DescribeCluster"
        )

        assert _collect_eks_clusters(session, ["eu-west-1"]) == []


class TestCollectEcrRepositories:
    def test_defaults_match_the_aws_defaults(self) -> None:
        session = MagicMock()
        _paginated(session, [{"repositories": [{"repositoryName": "app"}]}])

        repositories = _collect_ecr_repositories(session, ["eu-west-1"])

        assert repositories[0]["tag_mutability"] == "MUTABLE"
        assert repositories[0]["scan_on_push"] is False
        assert repositories[0]["encryption_type"] == "AES256"


class TestCollectLoadBalancers:
    def test_folds_listeners_and_attributes_into_the_balancer(self) -> None:
        session = MagicMock()
        client = _paginated(
            session,
            [
                {
                    "LoadBalancers": [
                        {
                            "LoadBalancerName": "public-alb",
                            "LoadBalancerArn": "arn:aws:elbv2:::lb/1",
                            "Scheme": "internet-facing",
                            "Type": "application",
                        }
                    ]
                }
            ],
        )
        client.describe_listeners.return_value = {
            "Listeners": [{"Port": 80, "Protocol": "HTTP"}]
        }
        client.describe_load_balancer_attributes.return_value = {
            "Attributes": [{"Key": "access_logs.s3.enabled", "Value": "false"}]
        }

        balancers = _collect_load_balancers(session, ["eu-west-1"])

        assert balancers[0]["listeners"] == [
            {"port": 80, "protocol": "HTTP", "ssl_policy": None}
        ]
        assert balancers[0]["access_logs_enabled"] is False
        assert balancers[0]["scheme"] == "internet-facing"


class TestCollectSecrets:
    def test_reports_rotation_without_reading_any_value(self) -> None:
        session = MagicMock()
        _paginated(
            session,
            [
                {
                    "SecretList": [
                        {
                            "Name": "prod/db",
                            "RotationEnabled": False,
                            "KmsKeyId": "arn:aws:kms:::key/a",
                        }
                    ]
                }
            ],
        )

        secrets = _collect_secrets(session, ["eu-west-1"])

        assert secrets[0]["rotation_enabled"] is False
        assert secrets[0]["rotation_days"] is None
        # list_secrets returns configuration only, and get_secret_value is
        # never called anywhere in the collector.
        assert "value" not in json.dumps(secrets)


class TestCollectKmsKeys:
    def test_reports_only_enabled_customer_managed_keys(self) -> None:
        # An AWS-managed key rotates on its own schedule and cannot be
        # configured, so reporting one would be noise nobody can act on.
        session = MagicMock()
        client = _paginated(
            session,
            [{"Keys": [{"KeyId": "cmk"}, {"KeyId": "aws-managed"}, {"KeyId": "gone"}]}],
        )
        client.describe_key.side_effect = lambda KeyId: {  # noqa: N803
            "cmk": {"KeyMetadata": {"KeyManager": "CUSTOMER", "KeyState": "Enabled"}},
            "aws-managed": {
                "KeyMetadata": {"KeyManager": "AWS", "KeyState": "Enabled"}
            },
            "gone": {
                "KeyMetadata": {
                    "KeyManager": "CUSTOMER",
                    "KeyState": "PendingDeletion",
                }
            },
        }[KeyId]
        client.get_key_rotation_status.return_value = {"KeyRotationEnabled": False}

        keys = _collect_kms_keys(session, ["eu-west-1"])

        assert [k["id"] for k in keys] == ["cmk"]
        assert keys[0]["rotation_enabled"] is False
