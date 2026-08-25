# METADATA
# title: GitHub App token wider or longer-lived than the job
# description: "A step mints a GitHub App installation token that outlives the job or reaches past the repository that asked for it. `actions/create-github-app-token` defaults are already least-privilege — with neither `owner` nor `repositories` set the token covers this repository alone, and it is revoked when the job ends. Both findings here are opt-outs from that: naming an `owner` without naming `repositories` widens the token to every repository in that owner's installation, and `skip-token-revoke: true` leaves a working credential behind after the run that created it has finished."
# custom:
#   severity: medium
#   severity_weight: 1.2
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         sync:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: actions/create-github-app-token@67e27a7eb7db372a1c61a7f9bdab8699e9ee57f7
#               id: app-token
#               with:
#                 app-id: ${{ vars.APP_ID }}
#                 private-key: ${{ secrets.APP_PRIVATE_KEY }}
#                 owner: ${{ github.repository_owner }}
#     good: |
#       jobs:
#         sync:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: actions/create-github-app-token@67e27a7eb7db372a1c61a7f9bdab8699e9ee57f7
#               id: app-token
#               with:
#                 app-id: ${{ vars.APP_ID }}
#                 private-key: ${{ secrets.APP_PRIVATE_KEY }}
#                 owner: ${{ github.repository_owner }}
#                 repositories: docs-site
#     fix: |
#       Name the repositories the job actually touches in `repositories:`, as a comma-separated list — the token is then scoped to exactly those and nothing else. If the job only needs this repository, drop `owner:` as well and let the action default. Remove `skip-token-revoke: true` unless something downstream genuinely needs the token after the job ends; if it does, revoke it explicitly at the end of that work instead of leaving it to expire.
package greensecops.ci_workflow.security.github_app_token_overbroad

import rego.v1

_is_app_token_step(step) if {
	contains(lower(object.get(step, "uses", "")), "actions/create-github-app-token")
}

# An empty string or an empty list is the same as not naming any repository —
# the action's own check is emptiness, not presence of the key.
_no_repositories(step) if not step["with"].repositories

_no_repositories(step) if trim_space(sprintf("%v", [step["with"].repositories])) == ""

_no_repositories(step) if count(step["with"].repositories) == 0

# `enterprise` is mutually exclusive with `owner`/`repositories` and scopes the
# token a different way entirely, so it is not this finding.
violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	_is_app_token_step(step)
	step["with"].owner
	not step["with"].enterprise
	_no_repositories(step)

	step_label := object.get(step, "name", "unnamed step")
	violation := {
		"rule": "github_app_token_overbroad",
		"severity": "medium",
		"category": "security",
		"job": job_name,
		"step": step.uses,
		"step_index": step_index,
		"message": sprintf("Step '%v' in job '%v' mints a GitHub App token with 'owner:' set but no 'repositories:', which scopes it to every repository in that owner's installation rather than the ones the job touches. List those repositories in 'repositories:', or drop 'owner:' and let the action default to this repository.", [step_label, job_name]),
		"context": "owner without repositories",
		"discriminator": sprintf("%v:%v:owner-scope", [job_name, step_index]),
	}
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	_is_app_token_step(step)
	lower(sprintf("%v", [step["with"]["skip-token-revoke"]])) in {"true", "1", "yes"}

	step_label := object.get(step, "name", "unnamed step")
	violation := {
		"rule": "github_app_token_overbroad",
		"severity": "medium",
		"category": "security",
		"job": job_name,
		"step": step.uses,
		"step_index": step_index,
		"message": sprintf("Step '%v' in job '%v' sets skip-token-revoke: true, so the GitHub App token stays valid after the job that minted it has finished. Remove the input and let the action revoke the token on job completion.", [step_label, job_name]),
		"context": "skip-token-revoke: true",
		"discriminator": sprintf("%v:%v:skip-revoke", [job_name, step_index]),
	}
}
