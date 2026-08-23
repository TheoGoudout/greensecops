import uuid
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint

from ..enums import Category, RuleDomain, Severity

if TYPE_CHECKING:
    from .issue import Issue


class Rule(SQLModel, table=True):
    # A slug is unique *within* an engine, not globally. The same finding is
    # real in more than one engine — `rds_not_encrypted` is a Terraform finding
    # and a live-account finding — and those are separate rules with separate
    # scores. While `slug` alone was unique, seeding inserted whichever engine
    # came first and skipped the rest, so `open_ingress_security_group`,
    # `rds_not_encrypted` and `s3_bucket_missing_versioning` had no cloud_aws
    # row at all and every finding they produced was dropped by cloud_scan's
    # `Rule.domain == cloud_aws` lookup (migration 0048).
    __table_args__ = (UniqueConstraint("domain", "slug", name="uq_rule_domain_slug"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    slug: str = Field(max_length=128, index=True)
    # Which analysis engine this rule belongs to. Existing rows all backfilled
    # to ``workflow`` (migration 0042); lets one Rule table and admin UI serve
    # the CI-workflow, Terraform and cloud engines.
    domain: RuleDomain = Field(
        default=RuleDomain.ci_workflow,
        sa_column_kwargs={"server_default": RuleDomain.ci_workflow.value},
    )
    category: Category
    severity: Severity
    title: str = Field(max_length=255)
    description: str = Field(max_length=2048)
    enabled: bool = Field(default=True)
    severity_weight: float = Field(default=1.0)
    issues: list["Issue"] = Relationship(back_populates="rule")
