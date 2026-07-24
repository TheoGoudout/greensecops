"""Read-only AWS resource collection for cloud posture scanning.

Assumes into the customer's role (``sts:AssumeRole`` + ``ExternalId`` —
static access keys are never accepted, see ``CloudAccount``'s docstring),
then runs a curated set of describe/list calls across security, cost, and
reliability-relevant resource types. Every resource type is collected
independently and defensively: one type failing (missing permission,
regional API hiccup) logs a warning and yields an empty list for that type
rather than aborting the whole scan — a partial posture picture is more
useful than none, and the missing-permission case itself is exactly the kind
of misconfiguration this feature exists to surface next scan once IAM is
fixed.

The normalized dict returned by :func:`collect_account_resources` is the OPA
input document for the ``cloud_aws`` policy domain — each key mirrors one
Rego rule's expected resource list shape.
"""

import json
import logging
import urllib.parse
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)

_SESSION_NAME = "greensecops-cloud-scan"
_DEFAULT_SESSION_DURATION_SECONDS = 900


class CloudCollectionError(Exception):
    """Raised when assuming the customer's role fails outright."""


def _base_sts_client() -> Any:  # noqa: ANN401 — boto3 client has no public stub type
    """The STS client for GreenSecOps's own identity — the one customer IAM
    roles grant ``sts:AssumeRole`` trust to.

    Explicit credentials when configured (``AWS_ACCESS_KEY_ID``/
    ``AWS_SECRET_ACCESS_KEY``), mirroring how ``services/storage/object_store``
    is explicit about its own S3 credentials rather than relying on an
    ambient chain. Falls back to boto3's default credential chain when unset,
    so a deployment that already runs on an AWS instance/task role (rather
    than static keys) still works without configuring anything.
    """
    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        return boto3.client(
            "sts",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_DEFAULT_REGION,
        )
    return boto3.client("sts", region_name=settings.AWS_DEFAULT_REGION)


def _assume_role_session(role_arn: str, external_id: str) -> boto3.Session:
    sts = _base_sts_client()
    try:
        resp = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName=_SESSION_NAME,
            ExternalId=external_id,
            DurationSeconds=_DEFAULT_SESSION_DURATION_SECONDS,
        )
    except (ClientError, BotoCoreError) as exc:
        raise CloudCollectionError(f"Could not assume role {role_arn}: {exc}") from exc

    creds = resp["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )


def _collect_s3_buckets(session: boto3.Session) -> list[dict[str, Any]]:
    client = session.client("s3")
    buckets: list[dict[str, Any]] = []
    try:
        names = [b["Name"] for b in client.list_buckets().get("Buckets", [])]
    except (ClientError, BotoCoreError) as exc:
        logger.warning("Failed to list S3 buckets: %s", exc)
        return []

    for name in names:
        block = {}
        try:
            block = client.get_public_access_block(Bucket=name)[
                "PublicAccessBlockConfiguration"
            ]
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in (
                "NoSuchPublicAccessBlockConfiguration",
            ):
                logger.warning("Failed to read access block for %s: %s", name, exc)

        encrypted = False
        try:
            rules = client.get_bucket_encryption(Bucket=name)[
                "ServerSideEncryptionConfiguration"
            ]["Rules"]
            encrypted = len(rules) > 0
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in (
                "ServerSideEncryptionConfigurationNotFoundError",
            ):
                logger.warning("Failed to read encryption for %s: %s", name, exc)

        versioning_enabled = False
        try:
            versioning_enabled = (
                client.get_bucket_versioning(Bucket=name).get("Status") == "Enabled"
            )
        except (ClientError, BotoCoreError) as exc:
            logger.warning("Failed to read versioning for %s: %s", name, exc)

        buckets.append(
            {
                "name": name,
                "block_public_acls": block.get("BlockPublicAcls", False),
                "block_public_policy": block.get("BlockPublicPolicy", False),
                "ignore_public_acls": block.get("IgnorePublicAcls", False),
                "restrict_public_buckets": block.get("RestrictPublicBuckets", False),
                "encrypted": encrypted,
                "versioning_enabled": versioning_enabled,
            }
        )
    return buckets


def _collect_security_groups(
    session: boto3.Session, regions: list[str]
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for region in regions:
        client = session.client("ec2", region_name=region)
        try:
            paginator = client.get_paginator("describe_security_groups")
            for page in paginator.paginate():
                for sg in page.get("SecurityGroups", []):
                    ingress_rules = [
                        {
                            "from_port": perm.get("FromPort"),
                            "to_port": perm.get("ToPort"),
                            "ip_protocol": perm.get("IpProtocol"),
                            "cidr_blocks": [
                                r["CidrIp"] for r in perm.get("IpRanges", [])
                            ]
                            + [r["CidrIpv6"] for r in perm.get("Ipv6Ranges", [])],
                        }
                        for perm in sg.get("IpPermissions", [])
                    ]
                    groups.append(
                        {
                            "id": sg["GroupId"],
                            "name": sg.get("GroupName", ""),
                            "region": region,
                            "ingress_rules": ingress_rules,
                        }
                    )
        except (ClientError, BotoCoreError) as exc:
            logger.warning("Failed to describe security groups in %s: %s", region, exc)
    return groups


def _collect_iam(
    session: boto3.Session,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    client = session.client("iam")
    users: list[dict[str, Any]] = []
    try:
        paginator = client.get_paginator("list_users")
        for page in paginator.paginate():
            for user in page.get("Users", []):
                mfa_enabled = False
                try:
                    devices = client.list_mfa_devices(UserName=user["UserName"])
                    mfa_enabled = len(devices.get("MFADevices", [])) > 0
                except (ClientError, BotoCoreError) as exc:
                    logger.warning(
                        "Failed to read MFA devices for %s: %s",
                        user["UserName"],
                        exc,
                    )
                users.append({"name": user["UserName"], "mfa_enabled": mfa_enabled})
    except (ClientError, BotoCoreError) as exc:
        logger.warning("Failed to list IAM users: %s", exc)

    policies: list[dict[str, Any]] = []
    try:
        paginator = client.get_paginator("list_policies")
        for page in paginator.paginate(Scope="Local"):
            for policy in page.get("Policies", []):
                statements: list[dict[str, Any]] = []
                try:
                    version = client.get_policy_version(
                        PolicyArn=policy["Arn"],
                        VersionId=policy["DefaultVersionId"],
                    )["PolicyVersion"]["Document"]
                    document = (
                        json.loads(urllib.parse.unquote(version))
                        if isinstance(version, str)
                        else version
                    )
                    raw_statements = document.get("Statement", [])
                    if isinstance(raw_statements, dict):
                        raw_statements = [raw_statements]
                    for stmt in raw_statements:
                        actions = stmt.get("Action", [])
                        if isinstance(actions, str):
                            actions = [actions]
                        resources = stmt.get("Resource", [])
                        if isinstance(resources, str):
                            resources = [resources]
                        statements.append(
                            {
                                "effect": stmt.get("Effect", "Deny"),
                                "actions": actions,
                                "resources": resources,
                            }
                        )
                except (ClientError, BotoCoreError) as exc:
                    logger.warning(
                        "Failed to read policy document for %s: %s",
                        policy["Arn"],
                        exc,
                    )
                policies.append(
                    {
                        "name": policy["PolicyName"],
                        "arn": policy["Arn"],
                        "statements": statements,
                    }
                )
    except (ClientError, BotoCoreError) as exc:
        logger.warning("Failed to list IAM policies: %s", exc)

    return users, policies


def _collect_rds_instances(
    session: boto3.Session, regions: list[str]
) -> list[dict[str, Any]]:
    instances: list[dict[str, Any]] = []
    for region in regions:
        client = session.client("rds", region_name=region)
        try:
            paginator = client.get_paginator("describe_db_instances")
            for page in paginator.paginate():
                for db in page.get("DBInstances", []):
                    instances.append(
                        {
                            "id": db["DBInstanceIdentifier"],
                            "region": region,
                            "publicly_accessible": db.get("PubliclyAccessible", False),
                            "storage_encrypted": db.get("StorageEncrypted", False),
                        }
                    )
        except (ClientError, BotoCoreError) as exc:
            logger.warning("Failed to describe RDS instances in %s: %s", region, exc)
    return instances


def _collect_ebs_volumes(
    session: boto3.Session, regions: list[str]
) -> list[dict[str, Any]]:
    volumes: list[dict[str, Any]] = []
    for region in regions:
        client = session.client("ec2", region_name=region)
        try:
            paginator = client.get_paginator("describe_volumes")
            for page in paginator.paginate():
                for vol in page.get("Volumes", []):
                    volumes.append(
                        {
                            "id": vol["VolumeId"],
                            "region": region,
                            "encrypted": vol.get("Encrypted", False),
                            "attached": len(vol.get("Attachments", [])) > 0,
                        }
                    )
        except (ClientError, BotoCoreError) as exc:
            logger.warning("Failed to describe EBS volumes in %s: %s", region, exc)
    return volumes


def _collect_lambda_functions(
    session: boto3.Session, regions: list[str]
) -> list[dict[str, Any]]:
    functions: list[dict[str, Any]] = []
    for region in regions:
        client = session.client("lambda", region_name=region)
        try:
            paginator = client.get_paginator("list_functions")
            for page in paginator.paginate():
                for fn in page.get("Functions", []):
                    public_url = False
                    try:
                        url_config = client.get_function_url_config(
                            FunctionName=fn["FunctionName"]
                        )
                        public_url = url_config.get("AuthType") == "NONE"
                    except ClientError as exc:
                        if (
                            exc.response.get("Error", {}).get("Code")
                            != "ResourceNotFoundException"
                        ):
                            logger.warning(
                                "Failed to read function URL config for %s: %s",
                                fn["FunctionName"],
                                exc,
                            )
                    functions.append(
                        {
                            "name": fn["FunctionName"],
                            "region": region,
                            "runtime": fn.get("Runtime", ""),
                            "public_url": public_url,
                        }
                    )
        except (ClientError, BotoCoreError) as exc:
            logger.warning("Failed to list Lambda functions in %s: %s", region, exc)
    return functions


def _collect_cloudtrail_trails(
    session: boto3.Session, regions: list[str]
) -> list[dict[str, Any]]:
    # CloudTrail is a near-global service: a single home-region API call
    # already returns every trail (including multi-region ones), so only the
    # first configured region is queried to avoid duplicate entries.
    if not regions:
        return []
    client = session.client("cloudtrail", region_name=regions[0])
    trails: list[dict[str, Any]] = []
    try:
        for trail in client.describe_trails(includeShadowTrails=False).get(
            "trailList", []
        ):
            is_logging = False
            try:
                is_logging = client.get_trail_status(Name=trail["TrailARN"]).get(
                    "IsLogging", False
                )
            except (ClientError, BotoCoreError) as exc:
                logger.warning(
                    "Failed to read trail status for %s: %s",
                    trail.get("Name"),
                    exc,
                )
            trails.append(
                {
                    "name": trail.get("Name", ""),
                    "region": trail.get("HomeRegion") or regions[0],
                    "is_logging": is_logging,
                }
            )
    except (ClientError, BotoCoreError) as exc:
        logger.warning("Failed to describe CloudTrail trails: %s", exc)
    return trails


def collect_account_resources(
    role_arn: str, external_id: str, regions: list[str]
) -> dict[str, Any]:
    """Assume into the account's role and collect the curated resource set.

    Raises :class:`CloudCollectionError` only when the role itself cannot be
    assumed (a genuine connectivity/trust failure); individual resource-type
    failures degrade to an empty list for that type instead of aborting.
    """
    session = _assume_role_session(role_arn, external_id)
    iam_users, iam_policies = _collect_iam(session)
    return {
        "s3_buckets": _collect_s3_buckets(session),
        "security_groups": _collect_security_groups(session, regions),
        "iam_users": iam_users,
        "iam_policies": iam_policies,
        "rds_instances": _collect_rds_instances(session, regions),
        "ebs_volumes": _collect_ebs_volumes(session, regions),
        "lambda_functions": _collect_lambda_functions(session, regions),
        "cloudtrail_trails": _collect_cloudtrail_trails(session, regions),
    }
