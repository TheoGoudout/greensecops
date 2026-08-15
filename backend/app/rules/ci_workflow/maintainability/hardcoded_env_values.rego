# METADATA
# title: Hardcoded environment-specific values
# description: "An environment variable pins a value that differs between environments — a deployment hostname, an account-specific bucket — directly in the workflow, so promoting the same workflow to another environment means editing it. Values that are the same everywhere are not this: loopback addresses, public package registries and documentation links mean one thing in every environment and belong in the file."
# custom:
#   severity: info
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         deploy:
#           env:
#             API_URL: https://api.production.example.com
#             BUCKET: my-app-artifacts
#           steps:
#             - run: ./deploy.sh
#     good: |
#       jobs:
#         deploy:
#           env:
#             API_URL: ${{ vars.API_URL }}
#             BUCKET: ${{ vars.ARTIFACT_BUCKET }}
#           steps:
#             - run: ./deploy.sh
#     fix: |
#       Move the value to a GitHub repository or environment variable and reference it with ${{ vars.NAME }}. Environment-scoped variables let the same workflow deploy to staging and production without a diff.
package greensecops.ci_workflow.maintainability.hardcoded_env_values

import data.greensecops.lib.workflow as wf
import rego.v1

# Hosts that mean the same thing in every environment. A loopback address is the
# clearest case — it is not "the production URL", it is "this runner", and no
# repository variable can make it more portable. This repository's own CI sets
# SERVICE_URL_BACKEND: http://localhost:8000 for a container it starts itself,
# and that was reported as an environment-specific value to externalise.
_environment_neutral_hosts := [
	"localhost",
	"127.0.0.1",
	"0.0.0.0",
	"[::1]",
	"host.docker.internal",
]

# Public infrastructure every environment talks to identically.
_environment_neutral_domains := [
	"registry.npmjs.org",
	"index.docker.io",
	"ghcr.io",
	"pypi.org",
	"files.pythonhosted.org",
	"crates.io",
	"proxy.golang.org",
	"github.com",
	"raw.githubusercontent.com",
	"api.github.com",
	"objects.githubusercontent.com",
	"deb.debian.org",
	"archive.ubuntu.com",
	"schema.org",
	"www.w3.org",
]

_url_host(value) := host if {
	rest := regex.replace(value, `^https?://`, "")
	host := split(split(split(rest, "/")[0], "?")[0], ":")[0]
}

_is_environment_neutral(value) if {
	host := _url_host(value)
	some neutral in _environment_neutral_hosts
	host == neutral
}

_is_environment_neutral(value) if {
	host := _url_host(value)
	some domain in _environment_neutral_domains
	endswith(host, domain)
}

# A `.local` name is mDNS on whatever machine is running; not portable, but not
# environment-specific either.
_is_environment_neutral(value) if endswith(_url_host(value), ".local")

_looks_like_url(value) if startswith(value, "http://")

_looks_like_url(value) if startswith(value, "https://")

_looks_like_bucket(value) if {
	some suffix in ["-bucket", "-artifacts", "-storage"]
	endswith(value, suffix)
}

_is_flagged_value(value) if {
	is_string(value)

	# Any `${{ }}` anywhere, not only at position 0 — the anchored test this
	# replaces reported `https://${{ vars.HOST }}/api`, which is already
	# externalised.
	not wf.is_expression(value)
	_looks_like_url(value)
	not _is_environment_neutral(value)
}

_is_flagged_value(value) if {
	is_string(value)
	not wf.is_expression(value)
	_looks_like_bucket(value)
}

_check_env(env, job_name) := {violation |
	some key, value in env
	_is_flagged_value(value)
	violation := {
		"rule": "hardcoded_env_values",
		"severity": "info",
		"category": "maintainability",
		"job": job_name,
		"message": sprintf("Env var '%v' pins an environment-specific value. Move it to a repository or environment variable and reference it with ${{ vars.NAME }}, so the same workflow works in every environment.", [key]),
		"context": key,
		"discriminator": key,
	}
}

violations contains violation if {
	some v in _check_env(input.env, null)
	violation := v
}

violations contains violation if {
	some job_name, job in input.jobs
	some v in _check_env(job.env, job_name)
	violation := v
}

violations contains violation if {
	some job_name, job in input.jobs
	some step in job.steps
	some v in _check_env(step.env, job_name)
	violation := v
}
