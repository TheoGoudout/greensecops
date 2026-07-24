"""Tests for the AWS resource collector's normalization logic.

Mirrors tests/services/test_app_client.py's approach to the GitHub client:
the AWS SDK boundary (boto3) is mocked the same way PyGithub is there — real
network/AWS calls aren't available in CI, so what's under test is GreenSecOps'
own normalization logic, not boto3 itself.
"""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from app.services.cloud.aws_collector import (
    CloudCollectionError,
    _assume_role_session,
    _collect_ebs_volumes,
    _collect_iam,
    _collect_rds_instances,
    _collect_s3_buckets,
    _collect_security_groups,
    collect_account_resources,
)


def _client_error(code: str, operation: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, operation)


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

        buckets = _collect_s3_buckets(session)

        assert buckets == [
            {
                "name": "my-bucket",
                "block_public_acls": True,
                "block_public_policy": False,
                "ignore_public_acls": True,
                "restrict_public_buckets": False,
                "encrypted": True,
                "versioning_enabled": True,
            }
        ]

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

        assert users == [
            {"name": "alice", "mfa_enabled": True},
            {"name": "bob", "mfa_enabled": False},
        ]
        assert policies == [
            {
                "name": "admin",
                "arn": "arn:aws:iam::1:policy/admin",
                "statements": [
                    {"effect": "Allow", "actions": ["*"], "resources": ["*"]}
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
            {"effect": "Allow", "actions": ["s3:GetObject"], "resources": ["*"]}
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
                "publicly_accessible": True,
                "storage_encrypted": False,
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
        }
