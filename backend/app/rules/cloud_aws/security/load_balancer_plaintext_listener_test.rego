package greensecops.cloud_aws.security.load_balancer_plaintext_listener_test

import data.greensecops.cloud_aws.security.load_balancer_plaintext_listener as plaintext
import rego.v1

_lb(scheme, listeners) := {"load_balancers": [{
	"name": "public-api",
	"arn": "arn:aws:elasticloadbalancing:eu-west-1:123456789012:loadbalancer/app/public-api/abc",
	"region": "eu-west-1",
	"scheme": scheme,
	"type": "application",
	"listeners": listeners,
	"access_logs_enabled": true,
	"drop_invalid_headers": true,
}]}

_listener(protocol, port) := {
	"port": port,
	"protocol": protocol,
	"ssl_policy": null,
}

test_violation_for_a_public_http_listener if {
	violations := plaintext.violations with input as _lb("internet-facing", [_listener("HTTP", 80)])
	count(violations) == 1
	some v in violations
	v.resource_id == "public-api"
	v.severity == "high"
}

test_violation_for_a_public_raw_tcp_listener if {
	violations := plaintext.violations with input as _lb("internet-facing", [_listener("TCP", 5432)])
	count(violations) == 1
}

test_no_violation_for_an_https_listener if {
	violations := plaintext.violations with input as _lb("internet-facing", [_listener("HTTPS", 443)])
	count(violations) == 0
}

test_no_violation_for_a_tls_listener if {
	violations := plaintext.violations with input as _lb("internet-facing", [_listener("TLS", 5432)])
	count(violations) == 0
}

# An internal balancer's plaintext listener stays inside the VPC — a defensible
# choice and a much smaller exposure than this rule reports.
test_no_violation_for_an_internal_balancer if {
	violations := plaintext.violations with input as _lb("internal", [_listener("HTTP", 80)])
	count(violations) == 0
}

test_no_violation_for_a_balancer_with_no_listeners if {
	violations := plaintext.violations with input as _lb("internet-facing", [])
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := plaintext.violations with input as {"load_balancers": []}
	count(violations) == 0
}

test_the_message_names_the_port if {
	violations := plaintext.violations with input as _lb("internet-facing", [_listener("HTTP", 8080)])
	some v in violations
	contains(v.message, "8080")
}

# The HTTPS listener beside it does not excuse the plaintext one, because a
# client that speaks to port 80 has already sent its request.
test_each_plaintext_listener_is_its_own_finding if {
	violations := plaintext.violations with input as _lb("internet-facing", [
		_listener("HTTP", 80),
		_listener("HTTP", 8080),
		_listener("HTTPS", 443),
	])
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
