"""The Ansible engine: projects, scans, findings and fixes."""

import uuid

from sqlmodel import Field, SQLModel

from .base import (
    FileFixPublicBase,
    FilePublicBase,
    FixablePublicBase,
    RepoScanPublicBase,
    ScanTargetPublicBase,
)


class AnsibleProjectCreate(SQLModel):
    repo_id: uuid.UUID
    # No default, unlike DockerTargetCreate: a project is registered by hand and
    # must say where it is. "" is still accepted for a repository-root project.
    root_path: str = Field(max_length=512)


class AnsibleProjectPublic(ScanTargetPublicBase):
    pass


class AnsibleScanPublic(RepoScanPublicBase):
    ansible_project_id: uuid.UUID
    file_count: int | None = None


class AnsibleFindingPublic(FixablePublicBase):
    ansible_project_id: uuid.UUID
    file_path: str
    # 1-based line span of the offending task or block, so the frontend can
    # annotate the finding inline on the YAML source.
    line_start: int | None = None
    line_end: int | None = None
    # The task's ``name:``. Null for a finding about a file rather than a task —
    # an unpinned galaxy requirement, or a credential in a variables file.
    task_name: str | None = None


class AnsibleFilePublic(FilePublicBase):
    """One Ansible file's live source for a project.

    Ansible files aren't persisted (unlike ``WorkflowFile``); they're fetched
    from GitHub on demand, so this carries no id or branch — just the path and
    content, mirroring ``TerraformFilePublic``.
    """

    # Which shape the classifier decided the file is: playbook, tasks,
    # handlers, vars or requirements. The frontend shows it as a chip, the way
    # the Docker file list shows dockerfile-vs-compose.
    kind: str


class AnsibleFixPublic(FileFixPublicBase):
    ansible_project_id: uuid.UUID
