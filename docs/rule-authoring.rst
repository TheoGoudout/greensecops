Writing rules
=============

A rule is two files: the policy and its test.

.. code-block:: text

   backend/app/rules/<engine>/<category>/<slug>.rego
   backend/app/rules/<engine>/<category>/<slug>_test.rego

The path is the rule's identity. ``<engine>`` selects which document the rule is
evaluated against, ``<category>`` is one of the five grading axes, and
``<slug>`` names the rule. The package declaration mirrors the path exactly
(``package greensecops.<engine>.<category>.<slug>``), and the rule exposes one
partial set called ``violations``.

Nothing else needs registering. The evaluator discovers the policy package from
the filesystem, and the ``rule`` table is seeded from the ``# METADATA`` block
by ``app.core.rule_registry`` — so a rule's severity, weight, title and
description are written once, in the file that implements it. Malformed
metadata fails the seed loudly rather than leaving the rule silently
unregistered, which is the failure mode the registry exists to remove.

Slugs are unique per engine, not globally. The same finding is genuinely a rule
in more than one engine — ``rds_not_encrypted`` is both a Terraform finding and
a live-account finding — and each keeps its own severity and score.

What a rule can see
-------------------

Each engine gets exactly one document, and rules cannot read across engines.

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Engine
     - Input document
   * - ``ci_workflow``
     - The parsed workflow YAML verbatim. No line numbers — see below.
   * - ``ci_telemetry``
     - ``{"runner_specs": {...}, "metrics": {...}}`` as measured by the Action.
   * - ``iac_terraform``
     - Every ``.tf`` in the root merged into one config, list-concatenated per block type.
   * - ``cloud_aws``
     - A normalized snapshot of eight AWS resource types.
   * - ``container_docker``
     - ``{"dockerfiles": [...], "compose_files": [...]}`` for the whole target.
   * - ``container_runtime``
     - ``{"build": {...}, "containers": [...]}`` from the Action's post step.

Traps worth knowing before writing a rule
-----------------------------------------

**Terraform values are frequently unresolved.** ``python-hcl2`` does not
evaluate expressions, so ``retention_in_days = var.log_retention_days`` arrives
as the string ``"${var.log_retention_days}"``. A rule that requires a literal
``true`` or a number therefore fires on every parameterised module, which is
most real Terraform. Absence-based rules treat an unresolved reference as
*configured*: the value is unknowable, but the decision was made deliberately.

**Absent is not false.** The AWS collector omits a field it could not read, and
the Action reports ``null`` for a container it never sampled. ``not x`` cannot
tell those apart from a genuine ``false``, so each rule has to decide which it
means — and say so in a test.

**A rule keyed on a missing field fires on every document.** Every engine's
rules are compiled together, so ``count(input.cloudtrail_trails) == 0`` is
vacuously true for a workflow, a Dockerfile and a Terraform config alike. Key on
the field being *present* and empty instead. The cross-domain check in
``scripts/validate_examples.py`` exists to catch this.

**Integer division breaks ``%f``.** Rego normalises a division that lands on a
whole number back to an integer, and ``sprintf``'s ``%f`` renders an integer as
``%!f(int=2)``. Round and use ``%v``, which is correct for both.

**Only the final Docker stage ships.** Scope rules about the shipped image to
``is_final``, or they fire on every builder stage that legitimately runs as
root.

**Compose overrides are not merged.** Each file is evaluated as it sits on
disk, so a rule that fires on the *absence* of a setting must skip documents
where ``is_override`` is true — the base file may well supply it.

Where the engines run out of signal
-----------------------------------

Several rules that would be worth having cannot be written today, because the
collectors do not gather what they would need. In rough order of value per unit
of work:

**The AWS collector is the binding constraint.**
``services/cloud/aws_collector.py`` returns eight resource types with a handful
of scalar fields each, and the existing rules already read nearly all of them.
Each of the following is a few lines in the collector and unlocks several
rules: S3 **bucket policies** (public-principal detection, which the ACL and
public-access-block rules cannot substitute for); security-group **egress**
(only ingress is collected); **KMS key identity** on EBS/RDS/S3, where today
there is only a boolean ``encrypted`` and so no way to distinguish a
customer-managed key from the AWS-managed default; IAM **access-key age and
last-used** via ``GetCredentialReport``; RDS ``backup_retention_period``,
``multi_az`` and ``auto_minor_version_upgrade``; CloudTrail **multi-region and
log-file validation**; Lambda **environment variables, VPC config and reserved
concurrency**; and the services not collected at all — CloudWatch log
retention, EKS, ECR, ELB/ALB listeners, Secrets Manager rotation.

**CI-workflow findings have no line numbers.** The OPA input is the parsed YAML
with no position data, so line attribution happens *after* evaluation, in a
second ruamel parse (``static_analysis._enrich_line_numbers``). It only
resolves a line when the violation names a job, and matches steps by
``step.uses`` — so any finding on a ``run:`` step has no line at all. Parsing
in round-trip mode and stamping ``__start_line__`` per job and step, exactly as
``services/docker/compose_parser.py`` already does, would fix attribution for
every existing rule at once and let rules reason about ordering directly.

**Compose merge semantics are not modelled.** Implementing the override and
``extends:`` merge would make the absence-based Compose rules sound on
multi-file projects, where they are currently skipped.

**There is no cross-engine input.** A rule cannot see a Compose file, the
Dockerfile it builds, and the workflow that builds them at once. The highest
value correlations need that — "this workflow builds this Dockerfile and skips
the cache the Dockerfile was written for" is not expressible in any single
engine.

**Whole input domains are absent**: Kubernetes and Helm manifests, SBOM and
dependency data, git and branch-protection metadata, other CI providers, other
clouds. Each needs a collector, an ``evaluate_*`` and violation dataclass in
``services/opa/evaluator.py``, a ``RuleDomain`` value, a findings table and a
Celery task — the six existing engines are the template. No rule-registration
work, though: the catalog follows from the files.
