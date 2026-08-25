"""The Terraform engine: roots, scans, findings and fixes."""

import uuid

from sqlmodel import Field, SQLModel

from .base import (
    FileFixPublicBase,
    FilePublicBase,
    FixablePublicBase,
    RepoScanPublicBase,
    ScanTargetPublicBase,
)


class TerraformRootCreate(SQLModel):
    repo_id: uuid.UUID
    root_path: str = Field(max_length=512)


class TerraformRootPublic(ScanTargetPublicBase):
    pass


class TerraformScanPublic(RepoScanPublicBase):
    terraform_root_id: uuid.UUID


class TerraformFindingPublic(FixablePublicBase):
    terraform_root_id: uuid.UUID
    resource_address: str | None = None
    file_path: str
    # 1-based line span of the offending block, when the scanner could locate
    # it — lets the frontend annotate the finding inline on the ``.tf`` source.
    line_start: int | None = None
    line_end: int | None = None
    # Directory-derived module locator + full Terraform address; null for
    # root-module resources. See ``hcl_parser.derive_module_path``.
    module_path: str | None = None
    terraform_address: str | None = None


class TerraformFilePublic(FilePublicBase):
    """A ``.tf`` file's live source for a Terraform root.

    Terraform files aren't persisted (unlike ``WorkflowFile``); they're fetched
    from GitHub on demand, so this carries no id/branch — just the path and
    content, mirroring the shape of ``WorkflowFilePublic``.
    """


class TerraformFixPublic(FileFixPublicBase):
    terraform_root_id: uuid.UUID
