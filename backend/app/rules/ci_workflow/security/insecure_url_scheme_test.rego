package greensecops.ci_workflow.security.insecure_url_scheme_test

import data.greensecops.ci_workflow.security.insecure_url_scheme as http_scheme
import rego.v1

test_violation_plaintext_download if {
	violations := http_scheme.violations with input as {"jobs": {"build": {"steps": [
		{"run": "curl -fsSL http://example.com/install.sh | bash"},
	]}}}
	count(violations) == 1
	some v in violations
	v.rule == "insecure_url_scheme"
	v.severity == "high"
}

# ─── Does not fire ───────────────────────────────────────────────────────────

test_no_violation_https if {
	violations := http_scheme.violations with input as {"jobs": {"build": {"steps": [
		{"run": "curl -fsSL https://example.com/install.sh | bash"},
	]}}}
	count(violations) == 0
}

# Traffic to a service the job started itself never leaves the machine. These
# are the values in this repository's own test workflows.
test_no_violation_loopback if {
	violations := http_scheme.violations with input as {"jobs": {"test": {"steps": [
		{"run": "curl http://localhost:8000/health"},
		{"run": "curl http://127.0.0.1:5173/"},
		{"run": "curl http://host.docker.internal:3000/"},
	]}}}
	count(violations) == 0
}

test_no_violation_url_in_a_comment if {
	violations := http_scheme.violations with input as {"jobs": {"build": {"steps": [
		{"run": "# see http://example.com/docs for why\nmake build"},
	]}}}
	count(violations) == 0
}

test_no_violation_step_without_run if {
	violations := http_scheme.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "actions/checkout@v4"},
	]}}}
	count(violations) == 0
}

test_no_violation_on_a_non_workflow_document if {
	violations := http_scheme.violations with input as {"resource": [{"aws_s3_bucket": {"b": {}}}]}
	count(violations) == 0
}

# ─── Shape ───────────────────────────────────────────────────────────────────

# Two plaintext URLs in one step are two findings, which needs the discriminator
# — the dedup key is (workflow, rule, job, step_index, discriminator).
test_each_url_is_its_own_finding if {
	violations := http_scheme.violations with input as {"jobs": {"build": {"steps": [
		{"run": "curl http://a.example.com/x\ncurl http://b.example.com/y"},
	]}}}
	count(violations) == 2
}

# An XML namespace is not a download. This fired at high severity on a heredoc
# writing a pom.xml.
test_no_violation_for_xml_namespace_in_heredoc if {
	violations := http_scheme.violations with input as {"jobs": {"b": {"steps": [{"run": concat("\n", [
		"cat > pom.xml <<EOF",
		"<project xmlns=\"http://maven.apache.org/POM/4.0.0\"/>",
		"EOF",
	])}]}}}
	count(violations) == 0
}

test_no_violation_for_a_url_in_an_echoed_message if {
	violations := http_scheme.violations with input as {"jobs": {"b": {"steps": [{"run": "echo \"docs at http://example.com/guide\""}]}}}
	count(violations) == 0
}

test_violation_survives_a_backslash_continuation if {
	violations := http_scheme.violations with input as {"jobs": {"b": {"steps": [{"run": "curl -fsSL \\\n  http://example.com/install.sh -o i.sh"}]}}}
	count(violations) == 1
}

test_violation_for_a_plaintext_package_index if {
	violations := http_scheme.violations with input as {"jobs": {"b": {"steps": [{"run": "pip install --index-url http://pypi.internal/simple pkg"}]}}}
	count(violations) == 1
}
