# METADATA
# title: Lambda function has no active tracing
# description: A Lambda function does not emit X-Ray traces, so when it is slow there is no way to see where the time goes. Duration metrics tell you a function took four seconds; they cannot tell you whether that was a cold start, a downstream call, or a retry loop — and those three have nothing in common as fixes. In a function that calls other services the trace is usually the only view that spans the boundary, which is exactly where the latency tends to be hiding.
# custom:
#   severity: low
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws lambda create-function --function-name checkout --runtime python3.12 \
#         --handler app.handler --role "$ROLE" --zip-file fileb://fn.zip
#     good: |
#       aws lambda update-function-configuration --function-name checkout \
#         --tracing-config Mode=Active
#     fix: |
#       Set the tracing mode to Active and give the execution role the AWSXRayDaemonWriteAccess policy. Sampling keeps the cost small — X-Ray records a fraction of requests by default rather than all of them.
package greensecops.cloud_aws.performance.lambda_tracing_disabled

import rego.v1

violations contains violation if {
	some fn in input.lambda_functions

	fn.tracing_enabled == false

	violation := {
		"rule": "lambda_tracing_disabled",
		"severity": "low",
		"category": "performance",
		"resource_type": "aws_lambda_function",
		"resource_id": fn.name,
		"region": fn.region,
		"message": sprintf("Function '%v' emits no traces, so a slow invocation cannot be attributed to a cold start, a downstream call or a retry.", [fn.name]),
	}
}
