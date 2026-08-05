package greensecops.ci_workflow.security.curl_pipe_shell_in_run_test

import data.greensecops.ci_workflow.security.curl_pipe_shell_in_run as curl_pipe_shell
import rego.v1

_job(steps) := {"jobs": {"setup": {"runs-on": "ubuntu-latest", "steps": steps}}}

test_violation_for_curl_piped_to_sh if {
	violations := curl_pipe_shell.violations with input as _job([{"run": "curl -sSL https://example.com/install.sh | sh"}])
	count(violations) == 1
	some v in violations
	v.job == "setup"
}

test_violation_for_curl_piped_to_bash if {
	violations := curl_pipe_shell.violations with input as _job([{"run": "curl -fsSL https://example.com/i.sh | bash"}])
	count(violations) == 1
}

test_violation_for_wget_piped_to_shell if {
	violations := curl_pipe_shell.violations with input as _job([{"run": "wget -qO- https://example.com/i.sh | sh"}])
	count(violations) == 1
}

test_violation_for_a_piped_sudo_shell if {
	violations := curl_pipe_shell.violations with input as _job([{"run": "curl -sSL https://example.com/i.sh | sudo bash"}])
	count(violations) == 1
}

test_violation_inside_a_multiline_script if {
	violations := curl_pipe_shell.violations with input as _job([{"run": "set -euo pipefail\ncurl -sSL https://example.com/i.sh | sh\nmake build\n"}])
	count(violations) == 1
}

# The fix: download, verify, then run as separate commands.
test_no_violation_for_download_verify_run if {
	violations := curl_pipe_shell.violations with input as _job([{"run": "curl -fsSL -o install.sh https://example.com/install.sh\necho 'a1b2 install.sh' | sha256sum -c -\nsh install.sh\n"}])
	count(violations) == 0
}

test_no_violation_for_a_plain_download if {
	violations := curl_pipe_shell.violations with input as _job([{"run": "curl -fsSL -o app.tar https://example.com/app.tar"}])
	count(violations) == 0
}

# Piping into a tool that is not a shell is not this finding.
test_no_violation_for_curl_piped_to_jq if {
	violations := curl_pipe_shell.violations with input as _job([{"run": "curl -sSL https://example.com/api | jq .version"}])
	count(violations) == 0
}

test_no_violation_for_a_uses_step if {
	violations := curl_pipe_shell.violations with input as _job([{"uses": "actions/setup-node@v5"}])
	count(violations) == 0
}

test_each_offending_step_is_its_own_finding if {
	violations := curl_pipe_shell.violations with input as _job([
		{"run": "curl -sSL https://a.example/i.sh | sh"},
		{"run": "make build"},
		{"run": "wget -qO- https://b.example/i.sh | bash"},
	])
	count(violations) == 2
	{v.step_index | some v in violations} == {0, 2}
}
