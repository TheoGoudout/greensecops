# METADATA
# title: Plaintext download in a run step
# description: "A run step fetches over http://. Anything on the path between the runner and the host can read and rewrite the response, and a download is usually a script or a binary the job then executes — so a rewritten response is code execution on the runner with whatever the job's token can reach. Loopback addresses are excluded: traffic to a service the job started itself never leaves the machine."
# custom:
#   severity: high
#   severity_weight: 2.0
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - run: curl -fsSL http://example.com/install.sh | bash
#     good: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - run: curl -fsSL https://example.com/install.sh | bash
#     fix: |
#       Use https://. If the host genuinely has no TLS, download over https from a mirror that does, or verify the payload against a checksum pinned in the workflow — an unauthenticated plaintext download of an executable is the weakest link in an otherwise pinned supply chain.
package greensecops.ci_workflow.security.insecure_url_scheme

import rego.v1

# Traffic to a service the job started itself never leaves the machine, so TLS
# would protect nothing. This repository's own CI talks to its containers on
# http://localhost:8000.
_loopback_pattern := `^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|host\.docker\.internal)([:/]|$)`

_code(run) := regex.replace(run, `#[^\n]*`, "")

# A set rather than a function returning one value: a step can fetch more than
# one plaintext URL, and each is its own finding.
_plaintext_urls(run) := {url |
	some url in regex.find_n(`http://[^\s'"$)\\;|]+`, _code(run), -1)
	not regex.match(_loopback_pattern, url)
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	run := step.run
	is_string(run)
	some url in _plaintext_urls(run)

	step_label := object.get(step, "name", "unnamed step")
	violation := {
		"rule": "insecure_url_scheme",
		"severity": "high",
		"category": "security",
		"job": job_name,
		"step_index": step_index,
		"message": sprintf("Step '%v' in job '%v' fetches %v over plaintext http. Anything on the path can rewrite the response, and a rewritten script or binary runs on the runner with the job's token.", [step_label, job_name, url]),
		"context": url,
		"discriminator": sprintf("%v:%v:%v", [job_name, step_index, url]),
	}
}
