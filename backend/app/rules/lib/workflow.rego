# Shared helpers for the ci_workflow rules.
#
# This package carries no METADATA and emits no `violations` — it is not a rule,
# and `rego_metadata.iter_rule_files` skips everything under `lib/` for that
# reason. It ships inside `rules/` anyway because `opa/Dockerfile` copies exactly
# that directory to `/policies`, so a helper package anywhere else would not
# resolve for the rules that import it.
#
# Everything here was extracted from a rule that already had it, usually from
# whichever copy was the most careful. Where two rules disagreed, the stricter
# reading won and the loose one is being fixed to match — `_is_secret_ref` was
# defined twice with different semantics (`hardcoded_secrets` tested two literal
# prefixes, `hardcoded_env_values` tested one), and both were wrong in ways that
# produced false positives on this repository's own workflows.
package greensecops.lib.workflow

import rego.v1

# ─── Expressions ─────────────────────────────────────────────────────────────

# True when `value` contains a `${{ ... }}` expression anywhere, not only at
# position 0. The anchored `startswith` this replaces missed
# `Bearer ${{ secrets.TOKEN }}` and `https://x@${{ secrets.HOST }}`, both of
# which are secret references and neither of which starts with the delimiter.
is_expression(value) if {
	is_string(value)
	regex.match(`\$\{\{.*\}\}`, value)
}

# True when `value` references a secret. Whitespace-tolerant, so `${{secrets.X}}`
# counts — the two-prefix `startswith(value, "${{ secrets.")` test it replaces
# treated that as a hardcoded literal.
references_secret(value) if {
	is_string(value)
	regex.match(`\$\{\{\s*secrets\.[A-Za-z0-9_-]+\s*\}\}`, value)
}

# True when `value` references a repository or environment variable.
references_var(value) if {
	is_string(value)
	regex.match(`\$\{\{\s*vars\.[A-Za-z0-9_-]+\s*\}\}`, value)
}

# Every string anywhere inside `node`, at any depth. Rules that ask "does this
# step mention X anywhere" reached for `json.marshal` before this existed, which
# is wrong twice over: Go's marshaller HTML-escapes `&`, `<` and `>`, so a
# pattern containing `&&` silently never matched a marshalled document, and the
# JSON punctuation between values can let a pattern span two unrelated fields.
# `walk` has neither problem — it yields the values themselves.
strings_within(node) := {value |
	walk(node, [_, value])
	is_string(value)
}

# The bodies of every `${{ ... }}` in `node`, as written. Checking these rather
# than the raw text is what keeps expression rules off shell syntax that merely
# looks similar — `test -f x && false || echo` in a `run:` script is control
# flow, not a GitHub expression.
expression_bodies(node) := {body |
	some text in strings_within(node)
	some body in regex.find_n(`\$\{\{[^}]*\}\}`, text, -1)
}

# ─── Action references ───────────────────────────────────────────────────────

# `owner/repo` from a `uses:` value, dropping any `@ref` and any subpath.
action_name(uses) := split(uses, "@")[0] if is_string(uses)

# The `@ref` half of a `uses:` value; undefined when there is none, so callers
# get a failed body rather than a bogus empty ref.
action_ref(uses) := ref if {
	is_string(uses)
	parts := split(uses, "@")
	count(parts) > 1
	ref := parts[1]
}

is_sha_pin(uses) if regex.match(`^[0-9a-f]{40}$`, action_ref(uses))

# A local reusable workflow (`./.github/workflows/x.yml`) or a Docker action.
# Neither is pinnable the way a published action is, so pinning rules must skip
# them rather than reporting an unfixable finding.
is_local_ref(uses) if {
	is_string(uses)
	startswith(uses, "./")
}

is_docker_ref(uses) if {
	is_string(uses)
	startswith(uses, "docker://")
}

# ─── Triggers ────────────────────────────────────────────────────────────────

# The set of trigger names, normalised across the three shapes `on:` can take:
# a bare string (`on: push`), a list (`on: [push, pull_request]`) and a mapping
# (`on: {push: {...}}`). Six rules each carried their own four-clause version of
# this; they disagreed, and the list form was untested in every one of them.
trigger_names := {name | some name, _ in input.on} if is_object(input.on)

trigger_names := {name | some name in input.on} if is_array(input.on)

trigger_names := {input.on} if is_string(input.on)

has_trigger(name) if name in trigger_names

# Triggers that run with a token in a context an outside contributor can reach.
runs_on_untrusted_input if {
	some trigger in ["pull_request_target", "issue_comment", "workflow_run"]
	has_trigger(trigger)
}

# ─── Runners ─────────────────────────────────────────────────────────────────

# The set of `runs-on` labels, normalised across the three shapes the key can
# take: a bare string (`runs-on: ubuntu-latest`), a list
# (`runs-on: [self-hosted, linux]`) and the group mapping
# (`runs-on: {group: gpu, labels: [a100]}`). Lower-cased, because runner labels
# are matched case-insensitively by GitHub.
#
# Three rules each carried their own version of this and they disagreed:
# `deprecated_runner_image` handled all three shapes, `runner_sizing` handled
# only the string, and `self_hosted_runner_public_trigger` handled the string
# and the list. A job on `runs-on: [self-hosted, gpu]` was therefore invisible
# to the sizing rules.
runs_on_labels(job) := {lower(job["runs-on"])} if is_string(job["runs-on"])

runs_on_labels(job) := {lower(label) | some label in job["runs-on"]; is_string(label)} if {
	is_array(job["runs-on"])
}

runs_on_labels(job) := {lower(label) | some label in job["runs-on"].labels; is_string(label)} if {
	is_object(job["runs-on"])
}

# ─── Jobs ────────────────────────────────────────────────────────────────────

# A job that calls a reusable workflow rather than running steps. GitHub rejects
# most job-level keys on these — `timeout-minutes` and `runs-on` among them — so
# a rule demanding one is asking for something the author cannot write.
is_reusable_call(job) if {
	is_string(job.uses)
	not job.steps
}

# `needs:` normalised across the scalar and list forms.
job_needs(job) := {job.needs} if is_string(job.needs)

job_needs(job) := {n | some n in job.needs} if is_array(job.needs)

# True when any job in the workflow reads an output of `job_name`, either
# through `needs.<job>.outputs.*` in an expression or by declaring outputs that
# reference it. This is what separates a `needs:` edge that carries data from
# one that only orders work.
job_outputs_consumed(job_name) if {
	some _, job in input.jobs
	regex.match(sprintf(`needs\.%v\.outputs\.`, [regex.replace(job_name, `[.*+?^${}()|\[\]\\]`, `\\$0`)]), json.marshal(job))
}
