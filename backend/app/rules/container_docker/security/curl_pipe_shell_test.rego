package greensecops.container_docker.security.curl_pipe_shell_test

import data.greensecops.container_docker.security.curl_pipe_shell
import rego.v1

_run(value, heredoc) := {"dockerfiles": [{
	"__docker_file": "Dockerfile",
	"final_stage": 0,
	"stages": [],
	"instructions": [{
		"instruction": "RUN",
		"value": value,
		"heredoc": heredoc,
		"stage": 0,
		"__start_line__": 4,
		"__end_line__": 4,
	}],
}]}

test_violation_for_curl_pipe_sh if {
	violations := curl_pipe_shell.violations with input as _run("curl -fsSL https://example.com/i.sh | sh", null)
	count(violations) == 1
}

test_violation_for_wget_pipe_bash if {
	violations := curl_pipe_shell.violations with input as _run("wget -qO- https://example.com/i.sh | bash", null)
	count(violations) == 1
}

test_violation_for_pipe_to_sudo_shell if {
	violations := curl_pipe_shell.violations with input as _run("curl -sL https://example.com/i.sh | sudo bash", null)
	count(violations) == 1
}

# The command lives in the heredoc body, not the instruction value.
test_violation_inside_heredoc_body if {
	violations := curl_pipe_shell.violations with input as _run("<<EOF", "curl -fsSL https://example.com/i.sh | sh")
	count(violations) == 1
}

test_no_violation_when_downloaded_to_a_file if {
	violations := curl_pipe_shell.violations with input as _run("curl -fsSL -o /tmp/i.sh https://example.com/i.sh && sh /tmp/i.sh", null)
	count(violations) == 0
}

# Piping into a non-shell consumer is not this rule's concern.
test_no_violation_when_piping_to_another_tool if {
	violations := curl_pipe_shell.violations with input as _run("curl -fsSL https://example.com/data.json | jq .version", null)
	count(violations) == 0
}
