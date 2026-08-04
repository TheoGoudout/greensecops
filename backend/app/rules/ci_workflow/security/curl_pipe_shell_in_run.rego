# METADATA
# title: Remote script piped straight into a shell
# description: A run step downloads a script and executes it in the same command, so whatever the URL returns at that moment runs on the runner with the job's token and secrets in its environment. Nothing verifies what came back, and the content can differ between the version a human reviewed and the version CI fetches — including per-request, since the server can see it is being piped. The workflow counterpart of the Docker engine's curl_pipe_shell rule.
# custom:
#   severity: high
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         setup:
#           runs-on: ubuntu-latest
#           steps:
#             - run: curl -sSL https://example.com/install.sh | sh
#     good: |
#       jobs:
#         setup:
#           runs-on: ubuntu-latest
#           steps:
#             - run: |
#                 curl -fsSL -o install.sh https://example.com/install.sh
#                 echo "a1b2c3d4e5f6 install.sh" | sha256sum -c -
#                 sh install.sh
#     fix: |
#       Download to a file, check it against a pinned checksum, then run it. Where the tool publishes a GitHub Action or a package, prefer that — it can be pinned to a SHA the way every other dependency is.
package greensecops.ci_workflow.security.curl_pipe_shell_in_run

import rego.v1

# Matches the same shapes as the Docker engine's rule so the two agree on what
# counts: a fetch, a pipe, and a shell on the other side of it.
_pipes_to_shell(script) if {
	regex.match(`(?i)(curl|wget)[^|;&\n]*\|\s*(sudo\s+)?(ba|z|k|da)?sh\b`, script)
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	script := step.run
	is_string(script)
	_pipes_to_shell(script)

	violation := {
		"rule": "curl_pipe_shell_in_run",
		"severity": "high",
		"category": "security",
		"job": job_name,
		"step_index": step_index,
		"message": sprintf("Job '%v' pipes a downloaded script straight into a shell, so whatever the URL returns runs on the runner with the job's secrets. Download it, verify a checksum, then run it.", [job_name]),
		"context": substring(script, 0, 300),
		"discriminator": sprintf("%v:%v", [job_name, step_index]),
	}
}
