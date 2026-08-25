# METADATA
# title: Secret parsed into fields the runner cannot redact
# description: "An expression runs fromJSON() over a secret and reads fields out of the result. The runner masks a secret by string-matching its literal value in the log stream, so it can hide the JSON blob it was given — but not the values pulled out of it. Every field the workflow reads is a distinct string the masker has never seen, and it prints in the clear. A secret stored as a JSON bundle is therefore disclosed by the act of using it."
# custom:
#   severity: high
#   severity_weight: 1.8
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         deploy:
#           runs-on: ubuntu-latest
#           steps:
#             - run: ./deploy.sh
#               env:
#                 DB_PASSWORD: ${{ fromJSON(secrets.DB_CREDENTIALS).password }}
#     good: |
#       jobs:
#         deploy:
#           runs-on: ubuntu-latest
#           steps:
#             - run: ./deploy.sh
#               env:
#                 DB_PASSWORD: ${{ secrets.DB_PASSWORD }}
#     fix: |
#       Split the bundle into one repository secret per field and reference each by name, so the runner masks the value that is actually used. Where the bundle has to stay whole, keep it whole: pass `${{ secrets.DB_CREDENTIALS }}` into a single env var and parse it inside the script, where the parsed fields never pass through the log stream.
package greensecops.ci_workflow.security.unredacted_secrets

import data.greensecops.lib.workflow as wf
import rego.v1

# A *named* secret, so this never overlaps `overprovisioned_secrets`, which owns
# the whole-context `toJSON(secrets)` case. GitHub's expression functions are
# case-insensitive, and both `fromJSON` and `fromJson` appear in the wild.
_PATTERN := `(?i)fromjson\s*\(\s*secrets\.[A-Za-z0-9_-]+\s*\)`

_parses_secret(value) if {
	is_string(value)
	regex.match(_PATTERN, value)
}

violations contains violation if {
	some key, value in input.env
	_parses_secret(value)

	violation := {
		"rule": "unredacted_secrets",
		"severity": "high",
		"category": "security",
		"job": null,
		"message": sprintf("Workflow-level env var '%v' parses a secret with fromJSON and reads a field out of it. The runner masks the whole secret, never the fields extracted from it, so that field prints in the clear in every job's log. Store the field as its own secret, or parse inside the script instead of in an expression.", [key]),
		"context": value,
		"discriminator": key,
	}
}

violations contains violation if {
	some job_name, job in input.jobs
	some key, value in job.env
	_parses_secret(value)

	violation := {
		"rule": "unredacted_secrets",
		"severity": "high",
		"category": "security",
		"job": job_name,
		"message": sprintf("Env var '%v' in job '%v' parses a secret with fromJSON and reads a field out of it. The runner masks the whole secret, never the fields extracted from it, so that field prints in the clear. Store the field as its own secret, or parse inside the script instead of in an expression.", [key, job_name]),
		"context": value,
		"discriminator": sprintf("%v:%v", [job_name, key]),
	}
}

# The step as a whole rather than key by key: `with:` inputs nest arbitrarily,
# and `run`/`if` are strings in their own right. A step is small enough that one
# finding per step is the right granularity — it names one place to edit.
violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	not _in_job_env(job, step)
	_parses_any(step)

	step_label := object.get(step, "name", "unnamed step")
	violation := {
		"rule": "unredacted_secrets",
		"severity": "high",
		"category": "security",
		"job": job_name,
		"step_index": step_index,
		"message": sprintf("Step '%v' in job '%v' parses a secret with fromJSON and reads a field out of it. The runner masks the whole secret, never the fields extracted from it, so that field prints in the clear. Store the field as its own secret, or parse inside the script instead of in an expression.", [step_label, job_name]),
		"context": "fromJSON(secrets.*)",
		"discriminator": sprintf("%v:%v", [job_name, step_index]),
	}
}

# A job-level env var is already reported once, against the job. Without this
# the step clause would report it again for every step that inherits it, which
# is the same line of YAML counted N times.
_in_job_env(job, step) if {
	some _, value in job.env
	_parses_secret(value)
	not _parses_any(step)
}

# Walks the node for its strings rather than marshalling it — `json.marshal`
# escapes `&`, `<` and `>`, and its punctuation can let a pattern span two
# unrelated fields.
_parses_any(node) if {
	some value in wf.strings_within(node)
	_parses_secret(value)
}
