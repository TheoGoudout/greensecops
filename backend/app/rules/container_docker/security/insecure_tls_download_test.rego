package greensecops.container_docker.security.insecure_tls_download_test

import data.greensecops.container_docker.security.insecure_tls_download
import rego.v1

# Mirrors app.services.docker.dockerfile_parser: a flat `instructions` list
# whose RUN entries carry `value` (with leading --flags already peeled off into
# `flags`) and `heredoc` for a BuildKit <<EOF body.

_df(instructions) := {"dockerfiles": [{
	"__docker_file": "Dockerfile",
	"final_stage": 0,
	"stages": [{"index": 0, "name": null, "is_final": true, "__start_line__": 1, "__end_line__": 9}],
	"instructions": instructions,
}]}

_run(value) := {
	"instruction": "RUN",
	"value": value,
	"flags": {},
	"stage": 0,
	"heredoc": null,
	"__start_line__": 3,
	"__end_line__": 3,
}

test_violation_for_curl_insecure_short_flag if {
	violations := insecure_tls_download.violations with input as _df([_run("curl -k -o app.tar https://example.com/app.tar")])
	count(violations) == 1
	some v in violations
	v.line_start == 3
}

test_violation_for_curl_insecure_long_flag if {
	violations := insecure_tls_download.violations with input as _df([_run("curl --insecure -O https://example.com/app.tar")])
	count(violations) == 1
}

test_violation_for_wget_no_check_certificate if {
	violations := insecure_tls_download.violations with input as _df([_run("wget --no-check-certificate https://example.com/app.tar")])
	count(violations) == 1
}

test_violation_for_pip_trusted_host if {
	violations := insecure_tls_download.violations with input as _df([_run("pip install --trusted-host pypi.org requests")])
	count(violations) == 1
}

test_violation_for_npm_strict_ssl_false if {
	violations := insecure_tls_download.violations with input as _df([_run("npm config set strict-ssl false && npm ci")])
	count(violations) == 1
}

test_violation_for_git_sslverify_false if {
	violations := insecure_tls_download.violations with input as _df([_run("git -c http.sslVerify=false clone https://example.com/repo")])
	count(violations) == 1
}

test_violation_inside_a_heredoc_body if {
	violations := insecure_tls_download.violations with input as _df([{
		"instruction": "RUN",
		"value": "<<EOF",
		"flags": {},
		"stage": 0,
		"heredoc": "set -eu\ncurl -k https://example.com/install.sh -o /tmp/i.sh\n",
		"__start_line__": 4,
		"__end_line__": 7,
	}])
	count(violations) == 1
}

test_violation_for_env_disabling_node_tls if {
	violations := insecure_tls_download.violations with input as _df([{
		"instruction": "ENV",
		"value": "NODE_TLS_REJECT_UNAUTHORIZED=0",
		"flags": {},
		"stage": 0,
		"heredoc": null,
		"__start_line__": 2,
		"__end_line__": 2,
	}])
	count(violations) == 1
	some v in violations
	contains(v.message, "every later build step")
}

test_no_violation_for_a_plain_download if {
	violations := insecure_tls_download.violations with input as _df([_run("curl -fsSL -o app.tar https://example.com/app.tar")])
	count(violations) == 0
}

test_no_violation_for_pip_install_without_the_flag if {
	violations := insecure_tls_download.violations with input as _df([_run("pip install --no-cache-dir requests")])
	count(violations) == 0
}

# `-k` is far too common a short option to match on its own; it only counts
# when the command is curl or wget.
test_no_violation_for_an_unrelated_dash_k if {
	violations := insecure_tls_download.violations with input as _df([_run("tar -k -xf archive.tar")])
	count(violations) == 0
}

test_no_violation_when_verification_is_explicitly_on if {
	violations := insecure_tls_download.violations with input as _df([_run("npm config set strict-ssl true && npm ci")])
	count(violations) == 0
}

test_each_offending_instruction_is_its_own_finding if {
	violations := insecure_tls_download.violations with input as _df([
		_run("curl -k https://a.example/x"),
		_run("wget --no-check-certificate https://b.example/y"),
		_run("curl -fsSL https://c.example/z"),
	])
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
