# METADATA
# title: Package published with a long-lived registry token
# description: "A step publishes to a package registry using an API token stored as a repository secret. Every major registry now accepts Trusted Publishing instead: the workflow proves its identity to the registry with a short-lived OIDC token minted per run and scoped to this repository and workflow. A stored token has none of those bounds — it does not expire, it works from anywhere, and anything that can read the secret can publish under the project's name until a human notices and revokes it."
# custom:
#   severity: high
#   severity_weight: 1.5
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         publish:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: pypa/gh-action-pypi-publish@76f52bc884231f62b9a034ebfe128415bbaabdfc
#               with:
#                 password: ${{ secrets.PYPI_API_TOKEN }}
#     good: |
#       jobs:
#         publish:
#           runs-on: ubuntu-latest
#           permissions:
#             id-token: write
#           steps:
#             - uses: pypa/gh-action-pypi-publish@76f52bc884231f62b9a034ebfe128415bbaabdfc
#     fix: |
#       Register this repository and workflow as a trusted publisher on the registry, grant the job `permissions: id-token: write`, and delete the token. For PyPI that means dropping the `password:` input from `pypa/gh-action-pypi-publish` entirely; for npm it means publishing with a recent npm CLI and no `NODE_AUTH_TOKEN`. Revoke the stored token afterwards — leaving it in the repository's secrets keeps the exposure the change was meant to remove.
package greensecops.ci_workflow.security.publish_without_trusted_publishing

import rego.v1

# One row per registry: how a publish is spelled in a `run:` script, and the
# environment variables that mean "authenticated with a stored token". Both
# halves are required, so a `npm publish --dry-run` in a job with no token is
# silent and a token sitting unused in the environment is silent too.
_registries := [
	{
		"name": "npm",
		"command": `(?:^|[\s;&|(])(?:npm|pnpm|bun)\s+publish\b`,
		"tokens": {"NODE_AUTH_TOKEN", "NPM_TOKEN", "NPM_AUTH_TOKEN"},
	},
	{
		"name": "PyPI",
		"command": `(?:^|[\s;&|(])(?:twine\s+upload|(?:python|python3|uv)\s+(?:-m\s+twine\s+upload|publish))\b`,
		"tokens": {"TWINE_PASSWORD", "TWINE_API_KEY", "PYPI_API_TOKEN", "UV_PUBLISH_TOKEN"},
	},
	{
		"name": "RubyGems",
		"command": `(?:^|[\s;&|(])gem\s+push\b`,
		"tokens": {"GEM_HOST_API_KEY", "RUBYGEMS_API_KEY"},
	},
	{
		"name": "crates.io",
		"command": `(?:^|[\s;&|(])cargo\s+publish\b`,
		"tokens": {"CARGO_REGISTRY_TOKEN"},
	},
]

# What the step can actually read: workflow env, job env and step env merged in
# precedence order. A token bound at any of the three is equally available to
# the publish command, and binding it at the top is if anything worse.
_visible_env(job, step) := merged if {
	merged := object.union(
		object.union(object.get(input, "env", {}), object.get(job, "env", {})),
		object.get(step, "env", {}),
	)
}

_token_authenticated(job, step, registry) := name if {
	script := step.run
	is_string(script)
	regex.match(registry.command, script)
	some name, _ in _visible_env(job, step)
	name in registry.tokens
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	some registry in _registries
	token := _token_authenticated(job, step, registry)

	step_label := object.get(step, "name", "unnamed step")
	violation := {
		"rule": "publish_without_trusted_publishing",
		"severity": "high",
		"category": "security",
		"job": job_name,
		"step_index": step_index,
		"message": sprintf("Step '%v' in job '%v' publishes to %v authenticated by '%v', a long-lived token that never expires and works from anywhere. Register this repository as a trusted publisher, grant the job 'permissions: id-token: write', drop the token from the step, and revoke it.", [step_label, job_name, registry.name, token]),
		"context": token,
		"discriminator": sprintf("%v:%v:%v", [job_name, step_index, registry.name]),
	}
}

# The PyPI publishing action is its own case: it authenticates through a
# `password:` input rather than the environment, and omitting that input is
# precisely how Trusted Publishing is selected. Presence of the input is
# therefore the whole finding.
violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	contains(lower(object.get(step, "uses", "")), "pypa/gh-action-pypi-publish")
	step["with"].password

	step_label := object.get(step, "name", "unnamed step")
	violation := {
		"rule": "publish_without_trusted_publishing",
		"severity": "high",
		"category": "security",
		"job": job_name,
		"step": step.uses,
		"step_index": step_index,
		"message": sprintf("Step '%v' in job '%v' publishes to PyPI with a 'password:' input, which is a stored API token. Omitting that input selects Trusted Publishing instead: register this repository and workflow on PyPI, grant the job 'permissions: id-token: write', delete the password line, and revoke the token.", [step_label, job_name]),
		"context": "pypa/gh-action-pypi-publish password:",
		"discriminator": sprintf("%v:%v:pypi-action", [job_name, step_index]),
	}
}
