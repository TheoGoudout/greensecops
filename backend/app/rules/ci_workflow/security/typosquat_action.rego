# METADATA
# title: Action name resembles a well-known action
# description: "A step uses an action whose repository name matches a widely-used GitHub action but whose owner does not. Confusing actions/checkout with action/checkout costs one character and hands the run's token to whoever registered the near-miss. Only distinctive names are checked, and known legitimate alternatives are listed by name — a generic name like cache has real third-party implementations and is not evidence of anything."
# custom:
#   severity: critical
#   severity_weight: 3.5
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: action/checkout@v4
#     good: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: actions/checkout@v4
#     fix: |
#       Correct the owner to the canonical one, then check the run history — if the wrong action ever executed, treat every secret the job could reach as disclosed and rotate it. Pinning to a commit SHA does not help here; a pin to the wrong repository is still the wrong repository.
package greensecops.ci_workflow.security.typosquat_action

import data.greensecops.lib.workflow as wf
import rego.v1

# Repository names distinctive enough that another owner using the same name is
# worth a second look. Deliberately excludes generic names — `cache` has
# legitimate third-party implementations (buildjet/cache), and flagging those
# would be noise rather than signal.
_canonical_owner_by_name := {
	"checkout": "actions",
	"setup-node": "actions",
	"setup-python": "actions",
	"setup-java": "actions",
	"setup-go": "actions",
	"setup-dotnet": "actions",
	"upload-artifact": "actions",
	"download-artifact": "actions",
	"github-script": "actions",
	"labeler": "actions",
	"stale": "actions",
	"dependency-review-action": "actions",
	"setup-uv": "astral-sh",
	"setup-bun": "oven-sh",
	"build-push-action": "docker",
	"login-action": "docker",
	"metadata-action": "docker",
	"setup-buildx-action": "docker",
	"configure-aws-credentials": "aws-actions",
	"wrangler-action": "cloudflare",
	"checkout-action": "actions",
}

# Forks and vendored copies that legitimately reuse a canonical name.
_allowed_alternatives := {"nektos/checkout"}

_repo_name(uses) := name if {
	full := wf.action_name(uses)
	parts := split(full, "/")
	count(parts) >= 2
	name := parts[1]
}

_owner(uses) := split(wf.action_name(uses), "/")[0]

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps

	uses := step.uses
	is_string(uses)
	not wf.is_local_ref(uses)

	name := _repo_name(uses)
	canonical := _canonical_owner_by_name[name]
	owner := _owner(uses)
	owner != canonical
	not wf.action_name(uses) in _allowed_alternatives

	violation := {
		"rule": "typosquat_action",
		"severity": "critical",
		"category": "security",
		"job": job_name,
		"step": uses,
		"step_index": step_index,
		"message": sprintf("Step in job '%v' uses '%v', but '%v' is published by '%v'. Confirm this is the action you meant — a near-miss owner receives the job's token exactly as the real one would.", [job_name, wf.action_name(uses), name, canonical]),
		"context": wf.action_name(uses),
		"discriminator": sprintf("%v:%v", [job_name, step_index]),
	}
}
