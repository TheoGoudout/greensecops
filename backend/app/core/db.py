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

# Mirrors TERRAFORM_INITIAL_RULES/CLOUD_INITIAL_RULES for the CI-workflow
# dynamic-telemetry engine — evaluated against a completed TelemetryRun's
# measured runner_specs/metrics (see workers/tasks/dynamic_analysis.py),
# not static YAML. Seeded for admin visibility/toggling like every other
# domain, even though DynamicEnrichment itself stays deliberately thinner
# than Issue/TerraformFinding/CloudFinding (no severity/category/rule_id
# columns — see its docstring) and isn't scored into a grade.
CI_TELEMETRY_INITIAL_RULES: list[dict[str, object]] = [
    {
        "slug": "runner_underutilized",
        "domain": RuleDomain.ci_telemetry,
        "category": IssueCategory.energy,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.0,
        "title": "Runner underutilized during the run",
        "description": "Actual telemetry from a completed workflow run shows a large runner (8+ vCPUs) with low measured CPU and RAM usage throughout the job, indicating the runner size is not justified by the real workload.",
    },
    {
        "slug": "high_memory_pressure",
        "domain": RuleDomain.ci_telemetry,
        "category": IssueCategory.reliability,
        "severity": IssueSeverity.high,
        "severity_weight": 1.8,
        "title": "Runner ran under high memory pressure",
        "description": "Telemetry from a completed workflow run shows RAM usage above 90% at collection time, which risks the OS OOM-killer terminating a build step or test process non-deterministically.",
    },
    {
        "slug": "runner_disk_pressure",
        "domain": RuleDomain.ci_telemetry,
        "category": IssueCategory.reliability,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.0,
        "title": "Runner ran low on free disk space",
        "description": 'The runner\'s declared free disk space at job start was below 2 GB, a common cause of intermittent "no space left on device" failures.',
    },
]


# Mirrors TERRAFORM_INITIAL_RULES for the Docker/Compose engine. Seeding is
# mandatory, not cosmetic: like the Terraform and cloud engines (and unlike
# ci_workflow, which auto-registers an unknown slug via
# static_analysis._register_rule_from_violation), docker_analysis drops a
# violation whose slug has no Rule row. A rego rule shipped without an entry
# here is silently invisible.
DOCKER_INITIAL_RULES: list[dict[str, object]] = [
    {
        "slug": "container_runs_as_root",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.security,
        "severity": IssueSeverity.high,
        "severity_weight": 1.8,
        "title": "Container image runs as root",
        "description": "The final build stage declares no USER instruction, or sets it back to root, so the shipped image runs its entrypoint as uid 0. Any container escape or code-execution bug then starts with full root in the container namespace.",
    },
    {
        "slug": "unpinned_base_image",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.reliability,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.0,
        "title": "Base image is not pinned",
        "description": "A FROM instruction references an image by a mutable tag rather than a digest, so the same Dockerfile produces different images over time. Takes the same position on base images that unpinned_actions takes on Actions.",
    },
    {
        "slug": "secret_in_build_arg",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.security,
        "severity": IssueSeverity.critical,
        "severity_weight": 3.5,
        "title": "Secret hardcoded in ARG or ENV",
        "description": "An ARG or ENV instruction whose name looks like a credential is given a literal default value. Build arguments and environment variables are recorded in the image metadata and readable by anyone who can pull the image.",
    },
    {
        "slug": "curl_pipe_shell",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.security,
        "severity": IssueSeverity.high,
        "severity_weight": 1.8,
        "title": "Remote script piped straight into a shell",
        "description": "A RUN instruction downloads a script with curl or wget and pipes it directly into a shell, so the build executes whatever the remote host serves at build time with no verification.",
    },
    {
        "slug": "add_remote_url",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.security,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.0,
        "title": "ADD used to fetch a remote URL",
        "description": "An ADD instruction takes a remote URL as its source. ADD fetches over the network with no checksum verification and silently auto-extracts archives.",
    },
    {
        "slug": "compose_privileged_container",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.security,
        "severity": IssueSeverity.critical,
        "severity_weight": 3.5,
        "title": "Compose service runs privileged",
        "description": "A service sets privileged true, which disables almost every container isolation boundary — all capabilities, unrestricted device access, and an unconfined seccomp/AppArmor profile.",
    },
    {
        "slug": "compose_docker_socket_mount",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.security,
        "severity": IssueSeverity.critical,
        "severity_weight": 3.5,
        "title": "Docker socket mounted into a container",
        "description": "A service bind-mounts /var/run/docker.sock. Anything that can talk to the Docker socket can start a container with the host filesystem mounted, so this grants root on the host.",
    },
    {
        "slug": "compose_host_network_mode",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.security,
        "severity": IssueSeverity.high,
        "severity_weight": 1.8,
        "title": "Compose service uses host networking",
        "description": "A service sets network_mode host, so it shares the host's network namespace, binds every port it opens on the host, and can reach services on the host loopback.",
    },
    {
        "slug": "compose_cap_add_sys_admin",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.security,
        "severity": IssueSeverity.high,
        "severity_weight": 1.8,
        "title": "Service grants SYS_ADMIN or ALL capabilities",
        "description": "A service adds CAP_SYS_ADMIN or ALL. SYS_ADMIN covers mount, pivot_root and cgroup manipulation, and is the usual route out of a container.",
    },
    {
        "slug": "compose_hardcoded_secret",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.security,
        "severity": IssueSeverity.high,
        "severity_weight": 1.8,
        "title": "Secret hardcoded in a Compose environment",
        "description": "A service's environment block sets a credential-looking variable to a literal value. Compose files are committed, so the value lives in version-control history.",
    },
    {
        "slug": "copy_before_dependency_install",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.energy,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.0,
        "title": "Source copied before dependencies are installed",
        "description": "A stage copies the whole build context before running its dependency install, so a one-character source edit invalidates the cache and rebuilds the entire dependency tree on every push.",
    },
    {
        "slug": "apt_cache_not_cleaned",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.energy,
        "severity": IssueSeverity.low,
        "severity_weight": 0.5,
        "title": "apt package lists left in the image",
        "description": "A RUN instruction installs packages with apt-get but never removes /var/lib/apt/lists, leaving tens of megabytes of stale package index in the layer forever.",
    },
    {
        "slug": "no_multistage_build",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.energy,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.0,
        "title": "Build toolchain shipped in a single-stage image",
        "description": "A single-stage Dockerfile installs a compiler or build toolchain, so packages needed only to produce the artifact ship in the final image and inflate every pull and push.",
    },
    {
        "slug": "heavy_base_image",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.energy,
        "severity": IssueSeverity.low,
        "severity_weight": 0.5,
        "title": "Final image uses a full-fat base",
        "description": "The final stage builds on a full distribution or language image where the publisher also ships a slim variant, typically several hundred megabytes of packages the application never calls.",
    },
    {
        "slug": "compose_missing_resource_limits",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.energy,
        "severity": IssueSeverity.low,
        "severity_weight": 0.5,
        "title": "Compose service declares no resource limits",
        "description": "A service sets neither a memory nor a CPU limit, so one runaway container can starve every other service on the host and nothing records what the workload actually needs.",
    },
    {
        "slug": "missing_healthcheck",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.reliability,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.0,
        "title": "Runnable image declares no HEALTHCHECK",
        "description": "The final stage defines a CMD or ENTRYPOINT but no HEALTHCHECK, so the runtime cannot distinguish a deadlocked or failing container from a healthy one.",
    },
    {
        "slug": "compose_missing_restart_policy",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.reliability,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.0,
        "title": "Compose service declares no restart policy",
        "description": "A service sets no restart policy, so Docker leaves it stopped after a crash or host reboot — the default is 'no'.",
    },
    {
        "slug": "compose_depends_on_without_condition",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.reliability,
        "severity": IssueSeverity.low,
        "severity_weight": 0.5,
        "title": "depends_on used without a health condition",
        "description": "A service declares depends_on in the short list form, which waits only for the dependency's container to be created rather than for the process inside it to be ready.",
    },
    {
        "slug": "compose_unpinned_image_tag",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.reliability,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.0,
        "title": "Compose service uses a floating image tag",
        "description": "A service references an image with no tag or with :latest, so two runs a week apart start different code and rolling back the Compose file does not roll back the image.",
    },
    {
        "slug": "maintainer_instruction_deprecated",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.maintainability,
        "severity": IssueSeverity.low,
        "severity_weight": 0.5,
        "title": "Deprecated MAINTAINER instruction",
        "description": "The Dockerfile uses MAINTAINER, deprecated since Docker 1.13 in favour of LABEL, and invisible to the OCI annotation conventions registries and scanners consume.",
    },
    {
        "slug": "compose_obsolete_version_key",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.maintainability,
        "severity": IssueSeverity.low,
        "severity_weight": 0.5,
        "title": "Obsolete top-level version key in a Compose file",
        "description": "The file declares a top-level version key. The Compose Specification dropped it, and current versions of Docker Compose warn on every invocation while ignoring the value.",
    },
    {
        "slug": "missing_oci_labels",
        "domain": RuleDomain.container_docker,
        "category": IssueCategory.maintainability,
        "severity": IssueSeverity.low,
        "severity_weight": 0.5,
        "title": "Image declares no OCI source label",
        "description": "The Dockerfile sets no org.opencontainers.image.source label, so a published image cannot be traced back to the repository that produced it.",
    },
]


# Mirrors DOCKER_INITIAL_RULES for the Docker *dynamic* engine — evaluated
# against measured build and runtime telemetry rather than source. Seeded like
# every other domain for admin visibility and toggling, even though
# DockerBuildEnrichment stays deliberately thinner than DockerFinding (no
# fingerprint, dedup or resolution lifecycle) and isn't scored into a grade.
DOCKER_RUNTIME_INITIAL_RULES: list[dict[str, object]] = [
    {
        "slug": "image_layer_cache_ineffective",
        "domain": RuleDomain.container_runtime,
        "category": IssueCategory.energy,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.0,
        "title": "Image layer cache is not being reused",
        "description": "Measured build telemetry shows most layers rebuilding rather than hitting the cache. The measured counterpart to copy_before_dependency_install, which infers the same problem from instruction order.",
    },
    {
        "slug": "oversized_image",
        "domain": RuleDomain.container_runtime,
        "category": IssueCategory.energy,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.0,
        "title": "Published image is very large",
        "description": "Measured image size is above the threshold where pull time and registry storage begin to dominate — the shipped artifact's actual size, not an inference from the Dockerfile's shape.",
    },
    {
        "slug": "bloated_build_context",
        "domain": RuleDomain.container_runtime,
        "category": IssueCategory.energy,
        "severity": IssueSeverity.low,
        "severity_weight": 0.5,
        "title": "Build context is far larger than the image",
        "description": "The context uploaded to the builder dwarfs the image it produces, which almost always means a missing or incomplete .dockerignore. Invisible to static analysis, which cannot see the context's contents.",
    },
    {
        "slug": "container_oom_killed",
        "domain": RuleDomain.container_runtime,
        "category": IssueCategory.reliability,
        "severity": IssueSeverity.high,
        "severity_weight": 1.8,
        "title": "Container was OOM-killed",
        "description": "Measured runtime state shows the kernel terminated the container for exceeding its memory limit.",
    },
    {
        "slug": "container_memory_limit_mismatch",
        "domain": RuleDomain.container_runtime,
        "category": IssueCategory.reliability,
        "severity": IssueSeverity.low,
        "severity_weight": 0.5,
        "title": "Memory limit is far above measured peak usage",
        "description": "The declared memory limit is many times the observed peak, reserving capacity the workload never uses.",
    },
    {
        "slug": "healthcheck_never_healthy",
        "domain": RuleDomain.container_runtime,
        "category": IssueCategory.reliability,
        "severity": IssueSeverity.high,
        "severity_weight": 1.8,
        "title": "Container never reached a healthy state",
        "description": "A healthcheck is defined but the container never passed it during the observed run — worse than having none, because the service looks correctly configured.",
    },
    {
        "slug": "container_unbounded_memory",
        "domain": RuleDomain.container_runtime,
        "category": IssueCategory.energy,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.0,
        "title": "Container ran with no memory limit",
        "description": "A container was observed doing real work with no memory limit declared. The measured counterpart to compose_missing_resource_limits — this one knows the peak, so the fix can name a number rather than guess one.",
    },
    {
        "slug": "container_near_memory_limit",
        "domain": RuleDomain.container_runtime,
        "category": IssueCategory.reliability,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.0,
        "title": "Container peaked close to its memory limit",
        "description": "Measured peak usage sits within a narrow margin of the declared limit. Nothing has failed yet — this is the reading that precedes an OOM kill, and only measurement shows it before the fact.",
    },
    {
        "slug": "container_cpu_throttled",
        "domain": RuleDomain.container_runtime,
        "category": IssueCategory.performance,
        "severity": IssueSeverity.medium,
        "severity_weight": 1.0,
        "title": "Container spent a large share of its scheduling periods throttled",
        "description": "The kernel held the container at its CPU quota in a significant fraction of scheduling periods. Invisible to static analysis, which cannot know what the workload tries to do.",
    },
]


def _seed_rules(session: Session) -> list[str]:
    """Insert any rules from INITIAL_RULES not already present.

    Returns the slugs of the rules that were newly inserted, so callers can
    detect when a release has shipped new rules.
    """
    new_slugs: list[str] = []
    for rule_data in (
        INITIAL_RULES
        + TERRAFORM_INITIAL_RULES
        + CLOUD_INITIAL_RULES
        + CI_TELEMETRY_INITIAL_RULES
        + DOCKER_INITIAL_RULES
        + DOCKER_RUNTIME_INITIAL_RULES
    ):
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
