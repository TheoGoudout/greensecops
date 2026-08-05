# METADATA
# title: Internet-facing load balancer accepts plaintext
# description: An internet-facing load balancer has a listener speaking HTTP or raw TCP, so credentials, session cookies and response bodies cross the public internet unencrypted and are readable by anything on the path. A redirect listener is the usual intent — take port 80 and send it to 443 — but a redirect is itself served over plaintext, and a client that never sees it (an API call, a webhook, anything not a browser) sends its payload in the clear first and gets the redirect afterwards, by which point the request is already on the wire.
# custom:
#   severity: high
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws elbv2 create-listener --load-balancer-arn "$ARN" \
#         --protocol HTTP --port 80 --default-actions Type=forward,TargetGroupArn="$TG"
#     good: |
#       aws elbv2 create-listener --load-balancer-arn "$ARN" \
#         --protocol HTTPS --port 443 --certificates CertificateArn="$CERT" \
#         --ssl-policy ELBSecurityPolicy-TLS13-1-2-2021-06 \
#         --default-actions Type=forward,TargetGroupArn="$TG"
#     fix: |
#       Serve the application on HTTPS and leave port 80 only as a redirect action, never a forward. Then send HSTS from the application so a browser stops using the plaintext port at all after its first visit.
package greensecops.cloud_aws.security.load_balancer_plaintext_listener

import rego.v1

_plaintext := {"HTTP", "TCP"}

violations contains violation if {
	some lb in input.load_balancers

	# An internal balancer's plaintext listener stays inside the VPC. That is a
	# defensible choice and a different, much smaller, exposure.
	lb.scheme == "internet-facing"

	some listener in lb.listeners
	listener.protocol in _plaintext

	violation := {
		"rule": "load_balancer_plaintext_listener",
		"severity": "high",
		"category": "security",
		"resource_type": "aws_lb",
		"resource_id": lb.name,
		"region": lb.region,
		"message": sprintf("Internet-facing load balancer '%v' accepts %v on port %v, so traffic to it crosses the internet unencrypted.", [lb.name, listener.protocol, listener.port]),
		"discriminator": sprintf("listener-%v", [listener.port]),
	}
}
