from sqlmodel import Session, create_engine, select

from app import crud
from app.core.config import settings
from app.models import (
    IssueCategory,
    IssueSeverity,
    Rule,
    RuleDomain,
    User,
    UserCreate,
)

engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))

INITIAL_RULES: list[dict[str, object]] = [
    # Energy
    {
        "slug": "runner_sizing",
        "category": IssueCategory.energy,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.0,
        "title": "Oversized runner for job complexity",
        "description": "Job uses a large runner (8+ vCPUs) but contains only lightweight steps like linting or unit tests. Downsize to a standard runner to reduce cost and carbon footprint.",
    },
    {
        "slug": "caching_missing",
        "category": IssueCategory.energy,
        "severity": IssueSeverity.high,
        "severity_weight": 1.5,
        "title": "Missing dependency cache",
        "description": "No cache action detected for package manager (pip, npm, gradle, cargo, etc.). Caching dependencies dramatically reduces build time and runner energy consumption.",
    },
    {
        "slug": "redundant_steps",
        "category": IssueCategory.energy,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.0,
        "title": "Redundant steps across jobs",
        "description": "Identical setup steps (checkout, dependency install) are duplicated across jobs without using reusable workflows or job outputs.",
    },
    {
        "slug": "artifact_reuse",
        "category": IssueCategory.energy,
        "severity": IssueSeverity.medium,
        "severity_weight": 0.8,
        "title": "Build artifacts not reused",
        "description": "Dependent jobs rebuild artifacts already produced by upstream jobs instead of downloading them via actions/download-artifact.",
    },
    {
        "slug": "parallel_opportunity",
        "category": IssueCategory.energy,
        "severity": IssueSeverity.low,
        "severity_weight": 0.6,
        "title": "Sequential jobs without dependency",
        "description": "Multiple jobs run sequentially but have no dependency on each other. Running them in parallel would reduce total pipeline duration and energy use.",
    },
    {
        "slug": "large_runner_justification",
        "category": IssueCategory.energy,
        "severity": IssueSeverity.low,
        "severity_weight": 0.7,
        "title": "Large runner without justification",
        "description": "A GPU or large runner is used but no compute-intensive steps (model training, heavy compilation) are present.",
    },
    # Reliability
    {
        "slug": "missing_timeout",
        "category": IssueCategory.reliability,
        "severity": IssueSeverity.high,
        "severity_weight": 1.5,
        "title": "Missing job timeout",
        "description": "Job has no timeout-minutes set. Without a timeout, a hung job will consume runner minutes until the 6-hour GitHub default limit, blocking other workflows.",
    },
    {
        "slug": "unpinned_actions",
        "category": IssueCategory.reliability,
        "severity": IssueSeverity.high,
        "severity_weight": 1.8,
        "title": "Action not pinned to SHA",
        "description": "Action uses a mutable tag (@main, @v1, @latest) instead of a full commit SHA. Mutable tags can introduce breaking changes silently.",
    },
    {
        "slug": "missing_concurrency",
        "category": IssueCategory.reliability,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.0,
        "title": "Missing concurrency group on PR workflow",
        "description": "PR-triggered workflow has no concurrency group. Multiple pushes to the same PR will queue redundant runs instead of cancelling the previous one.",
    },
    {
        "slug": "artifact_retention",
        "category": IssueCategory.reliability,
        "severity": IssueSeverity.low,
        "severity_weight": 0.5,
        "title": "No explicit artifact retention",
        "description": "Uploaded artifacts use the default 90-day retention. Set retention-days explicitly to control storage costs and data lifecycle.",
    },
    {
        "slug": "continue_on_error_abuse",
        "category": IssueCategory.reliability,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.2,
        "title": "continue-on-error masking failures",
        "description": "continue-on-error: true is set on a step that is not explicitly intended to be optional. This can silently hide real failures.",
    },
    {
        "slug": "missing_retry",
        "category": IssueCategory.reliability,
        "severity": IssueSeverity.low,
        "severity_weight": 0.6,
        "title": "No retry on flaky network step",
        "description": "Steps that download external dependencies or call external APIs have no retry logic, making the pipeline fragile to transient network failures.",
    },
    # Security
    {
        "slug": "excessive_token_permissions",
        "category": IssueCategory.security,
        "severity": IssueSeverity.critical,
        "severity_weight": 3.0,
        "title": "Excessive GITHUB_TOKEN permissions",
        "description": "Workflow uses permissions: write-all or does not restrict token scope. The GITHUB_TOKEN should follow least privilege — declare only the permissions actually needed.",
    },
    {
        "slug": "hardcoded_secrets",
        "category": IssueCategory.security,
        "severity": IssueSeverity.critical,
        "severity_weight": 4.0,
        "title": "Potential hardcoded secret",
        "description": "An environment variable name matches common secret patterns (API_KEY, TOKEN, PASSWORD, SECRET) and its value appears to be a literal string rather than a secret reference.",
    },
    {
        "slug": "untrusted_actions",
        "category": IssueCategory.security,
        "severity": IssueSeverity.high,
        "severity_weight": 2.0,
        "title": "Third-party action not pinned to SHA",
        "description": "A third-party action (not from actions/ or github/) is used without pinning to a full commit SHA. This is a supply-chain attack vector.",
    },
    {
        "slug": "pr_target_injection",
        "category": IssueCategory.security,
        "severity": IssueSeverity.critical,
        "severity_weight": 4.0,
        "title": "pull_request_target with PR head checkout",
        "description": "Workflow triggers on pull_request_target and checks out the PR head ref. This grants untrusted code access to repository secrets.",
    },
    {
        "slug": "oidc_not_used",
        "category": IssueCategory.security,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.5,
        "title": "Long-lived cloud credentials instead of OIDC",
        "description": "Workflow uses static cloud credentials (AWS_ACCESS_KEY_ID, etc.) stored as secrets instead of OIDC short-lived tokens.",
    },
    # Performance
    {
        "slug": "cache_key_too_broad",
        "category": IssueCategory.performance,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.0,
        "title": "Cache key never misses",
        "description": "Cache key does not include a hash of the lockfile, meaning the cache never invalidates when dependencies change.",
    },
    {
        "slug": "unnecessary_full_checkout",
        "category": IssueCategory.performance,
        "severity": IssueSeverity.low,
        "severity_weight": 0.5,
        "title": "Unnecessary full git history checkout",
        "description": "fetch-depth: 0 is used but no git history analysis (changelog generation, git log, blame) is present in the workflow.",
    },
    {
        "slug": "no_matrix_strategy",
        "category": IssueCategory.performance,
        "severity": IssueSeverity.low,
        "severity_weight": 0.6,
        "title": "Duplicated jobs without matrix strategy",
        "description": "Multiple nearly-identical jobs differ only in a parameter (OS, Node version, etc.) but do not use a matrix strategy.",
    },
    {
        "slug": "slow_setup_order",
        "category": IssueCategory.performance,
        "severity": IssueSeverity.low,
        "severity_weight": 0.5,
        "title": "Expensive steps before fast-fail checks",
        "description": "Long dependency installation steps run before quick lint/type-check steps. Reordering to fail fast reduces wasted compute.",
    },
    # Maintainability
    {
        "slug": "no_reusable_workflow",
        "category": IssueCategory.maintainability,
        "severity": IssueSeverity.medium,
        "severity_weight": 0.8,
        "title": "Duplicated workflow blocks",
        "description": "Identical job definitions appear across multiple workflow files without using reusable workflows (workflow_call trigger).",
    },
    {
        "slug": "hardcoded_env_values",
        "category": IssueCategory.maintainability,
        "severity": IssueSeverity.medium,
        "severity_weight": 0.8,
        "title": "Hardcoded environment-specific values",
        "description": "Values like URLs, bucket names, or region names are hardcoded in the workflow instead of being referenced from repository variables or secrets.",
    },
    {
        "slug": "workflow_too_complex",
        "category": IssueCategory.maintainability,
        "severity": IssueSeverity.low,
        "severity_weight": 0.5,
        "title": "Workflow exceeds complexity threshold",
        "description": "Workflow has more than 20 steps across jobs without using reusable workflows or composite actions to reduce complexity.",
    },
    {
        "slug": "missing_workflow_description",
        "category": IssueCategory.maintainability,
        "severity": IssueSeverity.info,
        "severity_weight": 0.2,
        "title": "Missing name on jobs or steps",
        "description": "Jobs or steps are missing a name field, making CI logs harder to read and debug.",
    },
]

# Mirrors INITIAL_RULES for the Terraform static-analysis engine — the two
# stay separate lists (rather than one combined list with mixed domains)
# so each is easy to scan/diff on its own, and are merged for seeding in
# _seed_rules.
TERRAFORM_INITIAL_RULES: list[dict[str, object]] = [
    {
        "slug": "s3_bucket_public_acl",
        "domain": RuleDomain.iac_terraform,
        "category": IssueCategory.security,
        "severity": IssueSeverity.high,
        "severity_weight": 1.8,
        "title": "S3 bucket with a public ACL",
        "description": 'An aws_s3_bucket resource sets acl to "public-read" or "public-read-write", making every object in the bucket readable (or writable) by anyone on the internet by default.',
    },
    {
        "slug": "open_ingress_security_group",
        "domain": RuleDomain.iac_terraform,
        "category": IssueCategory.security,
        "severity": IssueSeverity.critical,
        "severity_weight": 3.5,
        "title": "Security group open to the world",
        "description": "An aws_security_group ingress rule allows traffic from 0.0.0.0/0, exposing the port to the entire internet rather than a scoped CIDR range.",
    },
    {
        "slug": "unencrypted_ebs_volume",
        "domain": RuleDomain.iac_terraform,
        "category": IssueCategory.security,
        "severity": IssueSeverity.high,
        "severity_weight": 1.8,
        "title": "Unencrypted EBS volume",
        "description": "An aws_ebs_volume resource has no encrypted = true, leaving data at rest unencrypted.",
    },
    {
        "slug": "rds_not_encrypted",
        "domain": RuleDomain.iac_terraform,
        "category": IssueCategory.security,
        "severity": IssueSeverity.high,
        "severity_weight": 1.8,
        "title": "RDS instance not encrypted at rest",
        "description": "An aws_db_instance resource has no storage_encrypted = true, leaving the database's data at rest unencrypted.",
    },
    {
        "slug": "hardcoded_credentials_in_tf",
        "domain": RuleDomain.iac_terraform,
        "category": IssueCategory.security,
        "severity": IssueSeverity.critical,
        "severity_weight": 4.0,
        "title": "Hardcoded AWS access key",
        "description": "A resource attribute contains a literal string matching the AWS access key ID format (AKIA...), rather than a variable or a secrets-manager reference.",
    },
    {
        "slug": "s3_bucket_missing_versioning",
        "domain": RuleDomain.iac_terraform,
        "category": IssueCategory.reliability,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.0,
        "title": "S3 bucket without versioning",
        "description": "An aws_s3_bucket resource has no versioning block, so an accidental overwrite or delete of an object can't be recovered.",
    },
    {
        "slug": "resource_missing_tags",
        "domain": RuleDomain.iac_terraform,
        "category": IssueCategory.maintainability,
        "severity": IssueSeverity.low,
        "severity_weight": 0.5,
        "title": "Resource missing tags",
        "description": "A resource of a type that supports the tags argument has none set, making cost attribution and ownership harder to track.",
    },
    {
        "slug": "variable_missing_description",
        "domain": RuleDomain.iac_terraform,
        "category": IssueCategory.maintainability,
        "severity": IssueSeverity.low,
        "severity_weight": 0.4,
        "title": "Variable without a description",
        "description": "A variable block has no description, making it harder for other authors (and module consumers) to understand its purpose without reading the whole config.",
    },
]

# Mirrors TERRAFORM_INITIAL_RULES for the AWS cloud-posture engine — checks
# the same curated resource set the collector describes (see
# services/cloud/aws_collector.py), evaluated against live account state
# rather than static HCL.
CLOUD_INITIAL_RULES: list[dict[str, object]] = [
    {
        "slug": "s3_public_access_block_disabled",
        "domain": RuleDomain.cloud_aws,
        "category": IssueCategory.security,
        "severity": IssueSeverity.high,
        "severity_weight": 1.8,
        "title": "S3 bucket without a full public access block",
        "description": "A live S3 bucket does not have all four Block Public Access settings enabled, leaving a path for the bucket or its objects to become publicly accessible.",
    },
    {
        "slug": "s3_bucket_unencrypted",
        "domain": RuleDomain.cloud_aws,
        "category": IssueCategory.security,
        "severity": IssueSeverity.high,
        "severity_weight": 1.8,
        "title": "S3 bucket without default encryption",
        "description": "A live S3 bucket has no server-side encryption configuration, leaving objects stored unencrypted at rest unless a caller opts in per-object.",
    },
    {
        "slug": "open_ingress_security_group",
        "domain": RuleDomain.cloud_aws,
        "category": IssueCategory.security,
        "severity": IssueSeverity.critical,
        "severity_weight": 3.5,
        "title": "Live security group open to the world",
        "description": "A live EC2 security group has an ingress rule allowing traffic from 0.0.0.0/0 or ::/0, exposing the port to the entire internet rather than a scoped CIDR range.",
    },
    {
        "slug": "iam_policy_wildcard_action",
        "domain": RuleDomain.cloud_aws,
        "category": IssueCategory.security,
        "severity": IssueSeverity.critical,
        "severity_weight": 4.0,
        "title": "IAM policy grants a wildcard action",
        "description": 'A customer-managed IAM policy has an Allow statement with Action set to "*" (or a service-wide "service:*"), granting far more permission than almost any real workload needs.',
    },
    {
        "slug": "iam_user_no_mfa",
        "domain": RuleDomain.cloud_aws,
        "category": IssueCategory.security,
        "severity": IssueSeverity.high,
        "severity_weight": 1.8,
        "title": "IAM user without MFA",
        "description": "A live IAM user has no MFA device registered, so a leaked password alone is sufficient to authenticate as them.",
    },
    {
        "slug": "rds_publicly_accessible",
        "domain": RuleDomain.cloud_aws,
        "category": IssueCategory.security,
        "severity": IssueSeverity.critical,
        "severity_weight": 3.5,
        "title": "RDS instance is publicly accessible",
        "description": "A live RDS instance has PubliclyAccessible set to true, giving it a public endpoint reachable from the internet rather than only from within its VPC.",
    },
    {
        "slug": "rds_not_encrypted",
        "domain": RuleDomain.cloud_aws,
        "category": IssueCategory.security,
        "severity": IssueSeverity.high,
        "severity_weight": 1.8,
        "title": "RDS instance not encrypted at rest",
        "description": "A live RDS instance has StorageEncrypted set to false, leaving its data at rest unencrypted.",
    },
    {
        "slug": "ebs_volume_unencrypted",
        "domain": RuleDomain.cloud_aws,
        "category": IssueCategory.security,
        "severity": IssueSeverity.high,
        "severity_weight": 1.8,
        "title": "EBS volume not encrypted",
        "description": "A live EBS volume has Encrypted set to false, leaving its data at rest unencrypted.",
    },
    {
        "slug": "lambda_public_function_url",
        "domain": RuleDomain.cloud_aws,
        "category": IssueCategory.security,
        "severity": IssueSeverity.critical,
        "severity_weight": 3.5,
        "title": "Lambda function URL with no auth",
        "description": "A live Lambda function has a Function URL configured with AuthType NONE, making it callable by anyone on the internet without any IAM authentication.",
    },
    {
        "slug": "s3_bucket_missing_versioning",
        "domain": RuleDomain.cloud_aws,
        "category": IssueCategory.reliability,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.0,
        "title": "S3 bucket without versioning",
        "description": "A live S3 bucket has no versioning enabled, so an accidental overwrite or delete of an object can't be recovered.",
    },
    {
        "slug": "cloudtrail_logging_disabled",
        "domain": RuleDomain.cloud_aws,
        "category": IssueCategory.reliability,
        "severity": IssueSeverity.high,
        "severity_weight": 1.8,
        "title": "CloudTrail trail not logging",
        "description": "A live CloudTrail trail exists but is not actively logging, leaving API activity in the account unrecorded and unavailable for incident investigation.",
    },
    {
        "slug": "ebs_volume_unattached",
        "domain": RuleDomain.cloud_aws,
        "category": IssueCategory.maintainability,
        "severity": IssueSeverity.low,
        "severity_weight": 0.5,
        "title": "Unattached EBS volume",
        "description": "A live EBS volume is not attached to any instance, and is very likely a forgotten leftover still incurring storage cost with no owner tracking whether it's safe to delete.",
    },
    {
        "slug": "lambda_deprecated_runtime",
        "domain": RuleDomain.cloud_aws,
        "category": IssueCategory.maintainability,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.0,
        "title": "Lambda function on a deprecated runtime",
        "description": "A live Lambda function runs on a runtime AWS has deprecated (past its official end-of-support date), so it no longer receives security patches and is blocked from configuration updates until migrated.",
    },
]


def _seed_rules(session: Session) -> list[str]:
    """Insert any rules from INITIAL_RULES not already present.

    Returns the slugs of the rules that were newly inserted, so callers can
    detect when a release has shipped new rules.
    """
    new_slugs: list[str] = []
    for rule_data in INITIAL_RULES + TERRAFORM_INITIAL_RULES + CLOUD_INITIAL_RULES:
        existing = session.exec(
            select(Rule).where(Rule.slug == rule_data["slug"])
        ).first()
        if not existing:
            rule = Rule.model_validate(rule_data)
            session.add(rule)
            new_slugs.append(str(rule_data["slug"]))
    session.commit()
    return new_slugs


def init_db(session: Session) -> list[str]:
    """Create initial data and return the slugs of any newly seeded rules."""
    user = session.exec(
        select(User).where(User.email == settings.FIRST_SUPERUSER)
    ).first()
    if not user:
        user_in = UserCreate(
            email=settings.FIRST_SUPERUSER,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            is_superuser=True,
        )
        user = crud.create_user(session=session, user_create=user_in)

    return _seed_rules(session)
