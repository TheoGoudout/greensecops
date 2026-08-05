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
Rego rule's expected resource list shape, and every value is a list.

Two things are deliberately never collected, because a finding about them
would otherwise carry the thing it is reporting: **Secrets Manager payloads**
(only rotation configuration is read; ``GetSecretValue`` is not called) and
**Lambda environment variable values** (only names, the same call
``DockerLayer.instruction`` makes in discarding RUN text).

The IAM actions this needs are documented in ``docs/cloud-scanning.rst``;
AWS's managed ``SecurityAudit`` policy covers all of them.
"""

import csv
import io
import json
import logging
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)

_SESSION_NAME = "greensecops-cloud-scan"

# One hour rather than fifteen minutes. The session has to outlive the whole
# scan — there is no refresh — and a wide account across several regions no
# longer fits in fifteen. Capped by the customer role's own MaxSessionDuration,
# which AWS defaults to exactly this.
_DEFAULT_SESSION_DURATION_SECONDS = 3600

# Enough to overlap the network waits without opening a connection per region
# per service on a large account.
_MAX_COLLECTOR_THREADS = 8


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


def _as_list(value: Any) -> list[Any]:
    """AWS policy documents write a single-element field as a bare scalar."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _normalize_statements(document: Any) -> list[dict[str, Any]]:
    """Flatten a policy document's statements into the shape rules read.

    Shared by IAM policies and S3 bucket policies: both are IAM policy
    documents, and both arrive either as a dict or as a URL-encoded JSON
    string depending on the API. ``Principal`` only appears on resource
    policies, which is what makes public-access detection possible for a
    bucket and meaningless for an identity policy.
    """
    if isinstance(document, str):
        try:
            document = json.loads(urllib.parse.unquote(document))
        except (ValueError, TypeError):
            return []
    if not isinstance(document, dict):
        return []

    statements: list[dict[str, Any]] = []
    for stmt in _as_list(document.get("Statement")):
        if not isinstance(stmt, dict):
            continue
        principal = stmt.get("Principal")
        # `"Principal": {"AWS": "*"}` and `"Principal": "*"` mean the same
        # thing; flatten both so a rule tests one list.
        principals: list[Any] = []
        if isinstance(principal, dict):
            for value in principal.values():
                principals.extend(_as_list(value))
        else:
            principals.extend(_as_list(principal))

        statements.append(
            {
                "effect": stmt.get("Effect", "Deny"),
                "actions": _as_list(stmt.get("Action")),
                "resources": _as_list(stmt.get("Resource")),
                "principals": [str(p) for p in principals],
                # A statement open to the world is only actually open if
                # nothing narrows it; a rule needs to see whether one exists.
                "has_condition": bool(stmt.get("Condition")),
            }
        )
    return statements


def _bucket_policy_statements(client: Any, name: str) -> list[dict[str, Any]]:
    """The bucket's resource policy, or [] when it has none.

    A bucket policy is the one route to public that neither the ACL check nor
    the public-access-block check can see — a bucket can have a private ACL,
    no block, and a policy granting `s3:GetObject` to `*`.
    """
    try:
        return _normalize_statements(client.get_bucket_policy(Bucket=name)["Policy"])
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "NoSuchBucketPolicy":
            logger.warning("Failed to read bucket policy for %s: %s", name, exc)
    except BotoCoreError as exc:
        logger.warning("Failed to read bucket policy for %s: %s", name, exc)
    return []


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
        kms_key_id = None
        try:
            rules = client.get_bucket_encryption(Bucket=name)[
                "ServerSideEncryptionConfiguration"
            ]["Rules"]
            encrypted = len(rules) > 0
            # SSE-S3 reports aws:kms only when a key was actually chosen, so a
            # null here means the AWS-managed default rather than a CMK — the
            # distinction a rule needs to tell "encrypted" from "encrypted with
            # a key whose access you control".
            for rule in rules:
                default = rule.get("ApplyServerSideEncryptionByDefault", {})
                if default.get("KMSMasterKeyID"):
                    kms_key_id = default["KMSMasterKeyID"]
                    break
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

        logging_enabled = False
        try:
            logging_enabled = "LoggingEnabled" in client.get_bucket_logging(Bucket=name)
        except (ClientError, BotoCoreError) as exc:
            logger.warning("Failed to read logging config for %s: %s", name, exc)

        buckets.append(
            {
                "name": name,
                "block_public_acls": block.get("BlockPublicAcls", False),
                "block_public_policy": block.get("BlockPublicPolicy", False),
                "ignore_public_acls": block.get("IgnorePublicAcls", False),
                "restrict_public_buckets": block.get("RestrictPublicBuckets", False),
                "encrypted": encrypted,
                "kms_key_id": kms_key_id,
                "versioning_enabled": versioning_enabled,
                "logging_enabled": logging_enabled,
                "policy_statements": _bucket_policy_statements(client, name),
            }
        )
    return buckets


def _permission_rules(permissions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize an IpPermissions list, folding IPv4 and IPv6 CIDRs together."""
    return [
        {
            "from_port": perm.get("FromPort"),
            "to_port": perm.get("ToPort"),
            "ip_protocol": perm.get("IpProtocol"),
            "cidr_blocks": [r["CidrIp"] for r in perm.get("IpRanges", [])]
            + [r["CidrIpv6"] for r in perm.get("Ipv6Ranges", [])],
        }
        for perm in permissions
    ]


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
                    groups.append(
                        {
                            "id": sg["GroupId"],
                            "name": sg.get("GroupName", ""),
                            "region": region,
                            "ingress_rules": _permission_rules(
                                sg.get("IpPermissions", [])
                            ),
                            # Egress is what decides whether a compromised
                            # instance can reach the internet to exfiltrate or
                            # fetch a second stage. AWS's default group allows
                            # all of it, so this is rarely a deliberate choice.
                            "egress_rules": _permission_rules(
                                sg.get("IpPermissionsEgress", [])
                            ),
                        }
                    )
        except (ClientError, BotoCoreError) as exc:
            logger.warning("Failed to describe security groups in %s: %s", region, exc)
    return groups


# What a user's credential fields look like when the report is unavailable —
# the role lacks iam:GenerateCredentialReport, or it is still being built.
# Every value is None rather than a default, so a rule can tell "not measured"
# from "measured and fine" and stay quiet on the former.
_NO_CREDENTIAL_REPORT: dict[str, Any] = {
    "console_access": None,
    "access_key_age_days": None,
    "access_key_unused_days": None,
}


def _report_age_days(value: str, now: datetime) -> int | None:
    """Days since an ISO timestamp in the credential report, or None.

    The report writes "N/A" for a field that does not apply (a user with no
    access key) and "no_information" for one AWS has not recorded.
    """
    if not value or value in ("N/A", "no_information", "not_supported"):
        return None
    try:
        return (now - datetime.fromisoformat(value)).days
    except ValueError:
        return None


def _credential_report(client: Any) -> dict[str, dict[str, Any]]:
    """Per-user key age and last-use, keyed by user name.

    The only API that reports these — an access key's age is not on
    ``list_users``, and ``get_access_key_last_used`` is one call per key. The
    report is generated asynchronously, so a first call can return 404 while
    it builds; that degrades to no data rather than blocking the scan, and the
    next scan picks it up.
    """
    try:
        client.generate_credential_report()
        raw = client.get_credential_report()["Content"]
    except (ClientError, BotoCoreError) as exc:
        logger.warning("Failed to read the IAM credential report: %s", exc)
        return {}

    text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    now = datetime.now(timezone.utc)
    report: dict[str, dict[str, Any]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        name = row.get("user", "")
        if not name or name == "<root_account>":
            continue
        key_ages = [
            age
            for column in ("access_key_1_last_rotated", "access_key_2_last_rotated")
            if (age := _report_age_days(row.get(column, ""), now)) is not None
        ]
        unused = [
            age
            for column in ("access_key_1_last_used_date", "access_key_2_last_used_date")
            if (age := _report_age_days(row.get(column, ""), now)) is not None
        ]
        report[name] = {
            "console_access": row.get("password_enabled") == "true",
            # The oldest key is the one that decides whether this user has a
            # stale credential, and the *least* recently used the one that
            # decides whether a key is abandoned.
            "access_key_age_days": max(key_ages) if key_ages else None,
            "access_key_unused_days": max(unused) if unused else None,
        }
    return report


def _collect_iam(
    session: boto3.Session,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    client = session.client("iam")
    credentials = _credential_report(client)
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
                users.append(
                    {
                        "name": user["UserName"],
                        "mfa_enabled": mfa_enabled,
                        **credentials.get(user["UserName"], _NO_CREDENTIAL_REPORT),
                    }
                )
    except (ClientError, BotoCoreError) as exc:
        logger.warning("Failed to list IAM users: %s", exc)

    policies: list[dict[str, Any]] = []
    try:
        paginator = client.get_paginator("list_policies")
        for page in paginator.paginate(Scope="Local"):
            for policy in page.get("Policies", []):
                statements: list[dict[str, Any]] = []
                try:
                    statements = _normalize_statements(
                        client.get_policy_version(
                            PolicyArn=policy["Arn"],
                            VersionId=policy["DefaultVersionId"],
                        )["PolicyVersion"]["Document"]
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
                            "engine": db.get("Engine", ""),
                            "publicly_accessible": db.get("PubliclyAccessible", False),
                            "storage_encrypted": db.get("StorageEncrypted", False),
                            "kms_key_id": db.get("KmsKeyId"),
                            "backup_retention_days": db.get("BackupRetentionPeriod", 0),
                            "multi_az": db.get("MultiAZ", False),
                            "auto_minor_version_upgrade": db.get(
                                "AutoMinorVersionUpgrade", False
                            ),
                            "deletion_protection": db.get("DeletionProtection", False),
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
                            "kms_key_id": vol.get("KmsKeyId"),
                            "volume_type": vol.get("VolumeType", ""),
                            "size_gb": vol.get("Size", 0),
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
                            # Names only. The values are exactly the secrets a
                            # rule wants to know were put here, so shipping
                            # them would recreate the problem it reports — the
                            # same call DockerLayer.instruction makes in
                            # discarding RUN text.
                            "environment_names": sorted(
                                fn.get("Environment", {}).get("Variables", {}) or {}
                            ),
                            "vpc_configured": bool(
                                fn.get("VpcConfig", {}).get("SubnetIds")
                            ),
                            "tracing_enabled": fn.get("TracingConfig", {}).get("Mode")
                            == "Active",
                            "kms_key_id": fn.get("KMSKeyArn"),
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
                    # A single-region trail records nothing about activity in
                    # every other region, which is where an attacker who knows
                    # that will work.
                    "is_multi_region": trail.get("IsMultiRegionTrail", False),
                    "log_file_validation_enabled": trail.get(
                        "LogFileValidationEnabled", False
                    ),
                    "kms_key_id": trail.get("KmsKeyId"),
                }
            )
    except (ClientError, BotoCoreError) as exc:
        logger.warning("Failed to describe CloudTrail trails: %s", exc)
    return trails


def _collect_cloudwatch_log_groups(
    session: boto3.Session, regions: list[str]
) -> list[dict[str, Any]]:
    """Log groups, for retention and encryption.

    A group with no retention keeps every line forever and is billed for it
    forever. It is the cost curve nobody notices, because no single deploy
    makes it worse.
    """
    groups: list[dict[str, Any]] = []
    for region in regions:
        client = session.client("logs", region_name=region)
        try:
            paginator = client.get_paginator("describe_log_groups")
            for page in paginator.paginate():
                for group in page.get("logGroups", []):
                    groups.append(
                        {
                            "name": group.get("logGroupName", ""),
                            "region": region,
                            # Absent means "never expire", which is the
                            # default and the finding.
                            "retention_days": group.get("retentionInDays"),
                            "kms_key_id": group.get("kmsKeyId"),
                            "stored_bytes": group.get("storedBytes", 0),
                        }
                    )
        except (ClientError, BotoCoreError) as exc:
            logger.warning("Failed to describe log groups in %s: %s", region, exc)
    return groups


def _collect_eks_clusters(
    session: boto3.Session, regions: list[str]
) -> list[dict[str, Any]]:
    """EKS clusters, for control-plane exposure and audit logging."""
    clusters: list[dict[str, Any]] = []
    for region in regions:
        client = session.client("eks", region_name=region)
        try:
            paginator = client.get_paginator("list_clusters")
            for page in paginator.paginate():
                for name in page.get("clusters", []):
                    try:
                        cluster = client.describe_cluster(name=name)["cluster"]
                    except (ClientError, BotoCoreError) as exc:
                        logger.warning(
                            "Failed to describe EKS cluster %s: %s", name, exc
                        )
                        continue
                    vpc = cluster.get("resourcesVpcConfig", {})
                    enabled_logs: list[str] = []
                    for entry in cluster.get("logging", {}).get("clusterLogging", []):
                        if entry.get("enabled"):
                            enabled_logs.extend(entry.get("types", []))
                    clusters.append(
                        {
                            "name": name,
                            "region": region,
                            "version": cluster.get("version", ""),
                            "endpoint_public_access": vpc.get(
                                "endpointPublicAccess", False
                            ),
                            "endpoint_private_access": vpc.get(
                                "endpointPrivateAccess", False
                            ),
                            "public_access_cidrs": vpc.get("publicAccessCidrs", []),
                            "enabled_log_types": sorted(enabled_logs),
                            "secrets_encrypted": bool(cluster.get("encryptionConfig")),
                        }
                    )
        except (ClientError, BotoCoreError) as exc:
            logger.warning("Failed to list EKS clusters in %s: %s", region, exc)
    return clusters


def _collect_ecr_repositories(
    session: boto3.Session, regions: list[str]
) -> list[dict[str, Any]]:
    """ECR repositories, for tag mutability and scan-on-push."""
    repositories: list[dict[str, Any]] = []
    for region in regions:
        client = session.client("ecr", region_name=region)
        try:
            paginator = client.get_paginator("describe_repositories")
            for page in paginator.paginate():
                for repo in page.get("repositories", []):
                    repositories.append(
                        {
                            "name": repo.get("repositoryName", ""),
                            "region": region,
                            "tag_mutability": repo.get("imageTagMutability", "MUTABLE"),
                            "scan_on_push": repo.get(
                                "imageScanningConfiguration", {}
                            ).get("scanOnPush", False),
                            "encryption_type": repo.get(
                                "encryptionConfiguration", {}
                            ).get("encryptionType", "AES256"),
                        }
                    )
        except (ClientError, BotoCoreError) as exc:
            logger.warning("Failed to describe ECR repositories in %s: %s", region, exc)
    return repositories


def _collect_load_balancers(
    session: boto3.Session, regions: list[str]
) -> list[dict[str, Any]]:
    """ALBs and NLBs with their listeners, for plaintext and logging.

    Listeners are folded into the balancer rather than collected separately so
    a rule can say "this balancer serves plain HTTP" in one pass.
    """
    balancers: list[dict[str, Any]] = []
    for region in regions:
        client = session.client("elbv2", region_name=region)
        try:
            paginator = client.get_paginator("describe_load_balancers")
            for page in paginator.paginate():
                for lb in page.get("LoadBalancers", []):
                    arn = lb["LoadBalancerArn"]
                    listeners: list[dict[str, Any]] = []
                    try:
                        for listener in client.describe_listeners(
                            LoadBalancerArn=arn
                        ).get("Listeners", []):
                            listeners.append(
                                {
                                    "port": listener.get("Port"),
                                    "protocol": listener.get("Protocol", ""),
                                    "ssl_policy": listener.get("SslPolicy"),
                                }
                            )
                    except (ClientError, BotoCoreError) as exc:
                        logger.warning(
                            "Failed to describe listeners for %s: %s", arn, exc
                        )
                    attributes: dict[str, str] = {}
                    try:
                        attributes = {
                            a["Key"]: a["Value"]
                            for a in client.describe_load_balancer_attributes(
                                LoadBalancerArn=arn
                            ).get("Attributes", [])
                        }
                    except (ClientError, BotoCoreError) as exc:
                        logger.warning(
                            "Failed to describe attributes for %s: %s", arn, exc
                        )
                    balancers.append(
                        {
                            "name": lb.get("LoadBalancerName", ""),
                            "arn": arn,
                            "region": region,
                            "scheme": lb.get("Scheme", ""),
                            "type": lb.get("Type", ""),
                            "listeners": listeners,
                            "access_logs_enabled": attributes.get(
                                "access_logs.s3.enabled"
                            )
                            == "true",
                            "drop_invalid_headers": attributes.get(
                                "routing.http.drop_invalid_header_fields.enabled"
                            )
                            == "true",
                        }
                    )
        except (ClientError, BotoCoreError) as exc:
            logger.warning("Failed to describe load balancers in %s: %s", region, exc)
    return balancers


def _collect_secrets(
    session: boto3.Session, regions: list[str]
) -> list[dict[str, Any]]:
    """Secrets Manager entries — metadata only, never a secret value.

    ``list_secrets`` returns configuration and never the payload, and no
    ``get_secret_value`` call is made anywhere in this module.
    """
    secrets: list[dict[str, Any]] = []
    for region in regions:
        client = session.client("secretsmanager", region_name=region)
        try:
            paginator = client.get_paginator("list_secrets")
            for page in paginator.paginate():
                for secret in page.get("SecretList", []):
                    rotation_days = secret.get("RotationRules", {}).get(
                        "AutomaticallyAfterDays"
                    )
                    secrets.append(
                        {
                            "name": secret.get("Name", ""),
                            "region": region,
                            "rotation_enabled": secret.get("RotationEnabled", False),
                            "rotation_days": rotation_days,
                            "kms_key_id": secret.get("KmsKeyId"),
                        }
                    )
        except (ClientError, BotoCoreError) as exc:
            logger.warning("Failed to list secrets in %s: %s", region, exc)
    return secrets


def _collect_kms_keys(
    session: boto3.Session, regions: list[str]
) -> list[dict[str, Any]]:
    """Customer-managed KMS keys, for rotation.

    AWS-managed keys rotate on their own schedule and cannot be configured, so
    they are filtered out — reporting them would be noise nobody can act on.
    """
    keys: list[dict[str, Any]] = []
    for region in regions:
        client = session.client("kms", region_name=region)
        try:
            paginator = client.get_paginator("list_keys")
            for page in paginator.paginate():
                for entry in page.get("Keys", []):
                    key_id = entry["KeyId"]
                    try:
                        metadata = client.describe_key(KeyId=key_id)["KeyMetadata"]
                    except (ClientError, BotoCoreError) as exc:
                        logger.warning("Failed to describe KMS key %s: %s", key_id, exc)
                        continue
                    if metadata.get("KeyManager") != "CUSTOMER":
                        continue
                    if metadata.get("KeyState") != "Enabled":
                        continue
                    rotation_enabled = False
                    try:
                        rotation_enabled = client.get_key_rotation_status(
                            KeyId=key_id
                        ).get("KeyRotationEnabled", False)
                    except (ClientError, BotoCoreError) as exc:
                        logger.warning(
                            "Failed to read rotation status for %s: %s", key_id, exc
                        )
                    keys.append(
                        {
                            "id": key_id,
                            "region": region,
                            "description": metadata.get("Description", ""),
                            "rotation_enabled": rotation_enabled,
                        }
                    )
        except (ClientError, BotoCoreError) as exc:
            logger.warning("Failed to list KMS keys in %s: %s", region, exc)
    return keys


def collect_account_resources(
    role_arn: str, external_id: str, regions: list[str]
) -> dict[str, Any]:
    """Assume into the account's role and collect the curated resource set.

    Raises :class:`CloudCollectionError` only when the role itself cannot be
    assumed (a genuine connectivity/trust failure); individual resource-type
    failures degrade to an empty list for that type instead of aborting.
    """
    session = _assume_role_session(role_arn, external_id)

    # Run the resource types concurrently. They are independent read-only API
    # calls, and serially the fourteen of them across several regions can
    # outlast the assumed session — at which point the tail of the scan fails
    # with ExpiredToken and reports a partial account as a clean one. Bounded
    # so a wide multi-region account cannot open an unreasonable number of
    # connections or trip AWS's own request throttling.
    regional: dict[str, Any] = {
        "security_groups": _collect_security_groups,
        "rds_instances": _collect_rds_instances,
        "ebs_volumes": _collect_ebs_volumes,
        "lambda_functions": _collect_lambda_functions,
        "cloudtrail_trails": _collect_cloudtrail_trails,
        "cloudwatch_log_groups": _collect_cloudwatch_log_groups,
        "eks_clusters": _collect_eks_clusters,
        "ecr_repositories": _collect_ecr_repositories,
        "load_balancers": _collect_load_balancers,
        "secrets": _collect_secrets,
        "kms_keys": _collect_kms_keys,
    }

    resources: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=_MAX_COLLECTOR_THREADS) as pool:
        futures = {
            pool.submit(collector, session, regions): key
            for key, collector in regional.items()
        }
        futures[pool.submit(_collect_s3_buckets, session)] = "s3_buckets"
        iam_future = pool.submit(_collect_iam, session)

        for future in as_completed(futures):
            key = futures[future]
            try:
                resources[key] = future.result()
            except Exception:
                # Each collector already swallows API failures; anything
                # reaching here is a bug in normalization, and one resource
                # type is not worth failing the whole scan over.
                logger.exception("Collector for %s failed", key)
                resources[key] = []

        try:
            resources["iam_users"], resources["iam_policies"] = iam_future.result()
        except Exception:
            logger.exception("Collector for iam failed")
            resources["iam_users"], resources["iam_policies"] = [], []

    return resources
