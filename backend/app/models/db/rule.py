import uuid
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

from ..enums import IssueCategory, IssueSeverity, RuleDomain

if TYPE_CHECKING:
    from .issue import Issue


class Rule(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    slug: str = Field(max_length=128, unique=True, index=True)
    # Which analysis engine this rule belongs to. Existing rows all backfilled
    # to ``workflow`` (migration 0042); lets one Rule table and admin UI serve
    # the CI-workflow, Terraform and cloud engines.
    domain: RuleDomain = Field(
        default=RuleDomain.workflow,
        sa_column_kwargs={"server_default": RuleDomain.workflow.value},
    )
    category: IssueCategory
    severity: IssueSeverity
    title: str = Field(max_length=255)
    description: str = Field(max_length=2048)
    enabled: bool = Field(default=True)
    severity_weight: float = Field(default=1.0)
    issues: list["Issue"] = Relationship(back_populates="rule")
