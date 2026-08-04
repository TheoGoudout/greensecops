# METADATA
# title: SQS queue is not encrypted at rest
# description: An aws_sqs_queue sets neither kms_master_key_id nor sqs_managed_sse_enabled, so message bodies are stored unencrypted. Queues are routinely the place where a system's most sensitive payloads sit still for a while — password-reset tokens, webhook bodies, PII in transit between services — and unlike a database nobody thinks of a queue as storage, so this is rarely noticed.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       resource "aws_sqs_queue" "jobs" {
#         name = "jobs"
#       }
#     good: |
#       resource "aws_sqs_queue" "jobs" {
#         name                    = "jobs"
#         sqs_managed_sse_enabled = true
#       }
#     fix: |
#       Set sqs_managed_sse_enabled = true for SQS-managed encryption, or kms_master_key_id for a customer-managed key where you need to control rotation and access separately.
package greensecops.iac_terraform.security.sqs_queue_unencrypted

import rego.v1

violations contains violation if {
	some res in input.resource
	some name, queue in res.aws_sqs_queue
	not queue.kms_master_key_id
	not _sse_enabled(queue)
	violation := {
		"rule": "sqs_queue_unencrypted",
		"severity": "medium",
		"category": "security",
		"resource_address": sprintf("aws_sqs_queue.%v", [name]),
		"file_path": object.get(queue, "__tf_file", ""),
		"line_start": object.get(queue, "__start_line__", null),
		"line_end": object.get(queue, "__end_line__", null),
		"message": sprintf("SQS queue '%v' has no encryption at rest configured, so message bodies are stored in the clear.", [name]),
	}
}

_sse_enabled(queue) if queue.sqs_managed_sse_enabled == true

# hcl2 does not evaluate expressions, so `sqs_managed_sse_enabled = var.encrypt`
# arrives as the string "${var.encrypt}". A module that takes the setting as an
# input has made the decision deliberately; treating a reference as `false`
# would report every parameterised module.
_sse_enabled(queue) if {
	value := queue.sqs_managed_sse_enabled
	is_string(value)
	trim_space(value) != ""
}
