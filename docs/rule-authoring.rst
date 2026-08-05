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
     - The parsed workflow YAML, with ``__start_line__``/``__end_line__`` stamped on each job and each step.
   * - ``ci_telemetry``
     - ``{"runner_specs": {...}, "metrics": {...}}`` as measured by the Action.
   * - ``iac_terraform``
     - Every ``.tf`` in the root merged into one config, list-concatenated per block type.
   * - ``cloud_aws``
     - A normalized snapshot of fourteen AWS resource types.
   * - ``container_docker``
     - ``{"dockerfiles": [...], "compose_files": [...], "effective_compose_files": [...]}`` for the whole target — see the trap below on which Compose list to read.
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

**Compose targets give you two lists, and which one you read follows from what
you are asserting.** ``compose_files`` is the files as they sit on disk;
``effective_compose_files`` is one document per *configuration*, with a base
and its override merged the way Compose merges them.

- A rule firing on the **presence** of something dangerous reads
  ``compose_files``, so it reports the file the offending line is actually in.
- A rule firing on the **absence** of a setting reads
  ``effective_compose_files``, because absence is only meaningful about a
  complete configuration. A setting the override supplies is then not reported
  missing from the base, and a service the override introduces is graded rather
  than skipped.

Line spans and source paths are per *service*, not per document — a merged
service keeps the base's span, but a service only the override declares keeps
the override's. Prefer ``object.get(service, "__docker_file", object.get(cf,
"__docker_file", ""))`` over the document's path alone, or a finding will cite
a file the service does not appear in.

The merge follows Compose's asymmetry: scalars replaced, mappings merged
key-by-key, most sequences (``ports``, ``volumes``, ``cap_add``,
``security_opt``) **appended**, and ``command`` / ``entrypoint`` / ``env_file``
/ ``healthcheck`` replaced. That appending is what makes rules like
``compose_override_adds_capabilities`` necessary — a base's ``cap_drop: [ALL]``
does not cancel an override's ``cap_add``, so reading either file alone gives
the wrong answer. Not modelled: ``extends:``, ``!reset``/``!override``,
profiles, and ``${VAR}`` interpolation.

**Two findings on one line is noise, however true each one is.** When a new
rule would overlap an existing one, scope the new rule to what the old one does
not cover rather than letting both fire.
``compose_override_adds_capabilities`` excludes ``SYS_ADMIN`` and ``ALL``
because ``compose_cap_add_sys_admin`` already reports them;
``compose_override_exposes_bound_port`` excludes the datastore ports
``compose_port_bound_to_all_interfaces`` owns. What is left to the new rule is
the case nothing else reports, which is the part worth having.

Where the engines run out of signal
-----------------------------------

Several rules that would be worth having cannot be written today, because the
collectors do not gather what they would need. In rough order of value per unit
of work:

**An empty list and a missing permission are indistinguishable.** This is now
the sharpest constraint on cloud rule design. ``aws_collector`` collects each
resource type independently and, on an error, logs a warning and treats that
type as empty — a deliberate choice, since a partial picture beats none. The
cost is that ``count(input.eks_clusters) == 0`` means either "this account runs
no EKS" or "the role cannot call ``eks:ListClusters``", and no rule can tell
which.

So a cloud rule keys on a resource being **present and misconfigured**, never
on a list being empty. Where a rule genuinely needs the absence of something —
``ebs_uses_aws_managed_key`` infers "AWS-managed" from a key ARN matching
nothing in ``input.kms_keys`` — it must first assert the list is non-empty, and
accept the missed finding on an account that truly has none. Firing instead
would let an under-permissioned role manufacture a finding against every
encrypted resource it can see, which is the one failure mode
:doc:`cloud-scanning` commits against.

Fixing this properly means the collector distinguishing "collected, empty" from
"could not collect" in its output — a per-type status alongside the list — so a
rule can require the former. That is a small change to the collector and a
larger one to every rule that would use it.

**There is no cross-engine input.** A rule cannot see a Compose file, the
Dockerfile it builds, and the workflow that builds them at once. The highest
value correlations need that — "this workflow builds this Dockerfile and skips
the cache the Dockerfile was written for" is not expressible in any single
engine.

**Compose ``extends:`` is still unresolved.** The override merge is modelled
(see the trap above), but ``extends:`` is not: its ``file:`` key can point at
any path, including one ``classify_docker_file`` does not recognise, so it
needs a second fetch pass rather than a merge. The same applies to
``!reset``/``!override``, profiles and ``${VAR}`` interpolation, each of which
changes what runs in a way the merge does not model.

**Terraform has no cross-module resolution.** ``hcl_parser.derive_module_path``
is a directory heuristic rather than resolved ``module {}`` invocation, so a
rule cannot follow a variable from a root module into the child that consumes
it. Combined with hcl2 not evaluating expressions, this is why Terraform rules
treat an unresolved reference as configured.

**Whole input domains are absent**: Kubernetes and Helm manifests, SBOM and
dependency data, git and branch-protection metadata, other CI providers, other
clouds. Each needs a collector, an ``evaluate_*`` and violation dataclass in
``services/opa/evaluator.py``, a ``RuleDomain`` value, a findings table and a
Celery task — the six existing engines are the template. No rule-registration
work, though: the catalog follows from the files.
