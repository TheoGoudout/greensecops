# METADATA
# title: Workflow construct written to evade reading
# description: "A `uses:` path or a `${{ }}` expression is written in a form that means exactly what the plain form means, but does not look like it. GitHub normalises `owner//repo` and `owner/./repo` back to `owner/repo` before resolving the action, and `github['event']['issue']['title']` is the same read as `github.event.issue.title` — so neither spelling changes what runs. What changes is that a reviewer scanning the diff, and any tool matching on the obvious pattern, both miss it. There is no reason to write either form by hand, which is why it is worth reporting on sight."
# custom:
#   severity: medium
#   severity_weight: 1.0
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         triage:
#           runs-on: ubuntu-latest
#           steps:
#             - run: echo "${{ github['event']['issue']['title'] }}"
#     good: |
#       jobs:
#         triage:
#           runs-on: ubuntu-latest
#           steps:
#             - run: echo "$TITLE"
#               env:
#                 TITLE: ${{ github.event.issue.title }}
#     fix: |
#       Rewrite the construct in its plain form — `owner/repo` for a `uses:` path, dotted access for a context read — so the diff shows what it does. Then look at why it was written that way: an expression hidden behind bracket indexing is usually hiding an untrusted context read, and once it is in the open the ordinary rules about interpolating `github.event.*` into a script apply to it.
package greensecops.ci_workflow.security.obfuscated_workflow_construct

import data.greensecops.lib.workflow as wf
import rego.v1

# ─── Obfuscated `uses:` paths ────────────────────────────────────────────────

# `docker://` is a scheme, not a redundant separator, and a local ref genuinely
# begins `./`. Both are excluded before the path is examined rather than being
# special-cased in the pattern.
_obfuscated_uses(uses) if {
	is_string(uses)
	not wf.is_docker_ref(uses)
	path := wf.action_name(uses)
	trimmed := trim_prefix(path, "./")
	some pattern in [`//`, `/\./`, `/\.\./`]
	regex.match(pattern, trimmed)
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	_obfuscated_uses(step.uses)

	violation := {
		"rule": "obfuscated_workflow_construct",
		"severity": "medium",
		"category": "security",
		"job": job_name,
		"step": step.uses,
		"step_index": step_index,
		"message": sprintf("Step in job '%v' references '%v', whose path carries redundant separators or traversal. GitHub normalises it away before resolving the action, so the reference runs something the path does not plainly name. Write the plain 'owner/repo' form.", [job_name, step.uses]),
		"context": step.uses,
		"discriminator": sprintf("%v:%v:uses", [job_name, step_index]),
	}
}

# ─── Obfuscated expressions ──────────────────────────────────────────────────

# A context indexed by a *string literal*. The dynamic form — `secrets[format(...)]`,
# `secrets[matrix.name]` — is a legitimate pattern with no dotted equivalent, so
# the literal is what separates evasion from a real lookup.
_LITERAL_INDEX := `(?:github|env|vars|secrets|inputs|needs|steps|job|jobs|runner|strategy|matrix)\s*\[\s*'[^']*'\s*\]`

# A round trip that cannot change its argument, used only to break up a
# recognisable context read.
_NOOP_ROUNDTRIP := `(?i)(?:fromjson\s*\(\s*tojson|tojson\s*\(\s*fromjson)\s*\(`

# Only the inside of a `${{ }}` is examined. Checking raw text would report
# shell associative-array reads — `${config['name']}` in a run script — which
# are not GitHub expressions at all.
_obfuscated_expression(node) if {
	some body in wf.expression_bodies(node)
	some pattern in [_LITERAL_INDEX, _NOOP_ROUNDTRIP]
	regex.match(pattern, body)
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	_obfuscated_expression(step)

	step_label := object.get(step, "name", "unnamed step")
	violation := {
		"rule": "obfuscated_workflow_construct",
		"severity": "medium",
		"category": "security",
		"job": job_name,
		"step_index": step_index,
		"message": sprintf("Step '%v' in job '%v' reads a context through bracket indexing with a literal key, or through a fromJSON/toJSON round trip. Both mean exactly what the dotted form means and exist only to make the read harder to spot. Rewrite it as dotted access, then treat whatever it reads as the untrusted input it probably is.", [step_label, job_name]),
		"context": "obfuscated expression",
		"discriminator": sprintf("%v:%v:expression", [job_name, step_index]),
	}
}

violations contains violation if {
	some job_name, job in input.jobs
	_obfuscated_expression(job["if"])

	violation := {
		"rule": "obfuscated_workflow_construct",
		"severity": "medium",
		"category": "security",
		"job": job_name,
		"message": sprintf("Job '%v' has an if: that reads a context through bracket indexing with a literal key, or through a fromJSON/toJSON round trip. Both are the dotted form written so as not to look like it. Rewrite it as dotted access.", [job_name]),
		"context": job["if"],
		"discriminator": sprintf("%v:job-if", [job_name]),
	}
}
