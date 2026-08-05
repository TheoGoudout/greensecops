# METADATA
# title: Very large instance type declared
# description: An aws_instance or launch template asks for one of the largest instance sizes. These are legitimate for genuinely large workloads, but they are also what a "make it faster" change reaches for, and nothing later revisits the size — an instance runs at its declared size whether or not the work needs it, so an oversized choice is paid continuously in cost and in energy. It is the infrastructure equivalent of the runner_sizing check, and like that one it is a prompt to measure rather than a certainty.
# custom:
#   severity: medium
#   detection: pattern_matching
#   examples:
#     bad: |
#       resource "aws_instance" "worker" {
#         ami           = "ami-0123456789abcdef0"
#         instance_type = "m5.16xlarge"
#       }
#     good: |
#       resource "aws_instance" "worker" {
#         ami           = "ami-0123456789abcdef0"
#         instance_type = "m5.2xlarge"
#       }
#     fix: |
#       Check measured CPU and memory use before keeping the size. Where the load is bursty or periodic, an autoscaling group of smaller instances costs less than one large instance sized for the peak, and it survives losing a host.
package greensecops.iac_terraform.energy.oversized_instance_type

import rego.v1

# 8xlarge and up. Anything smaller is an ordinary sizing decision, and the
# rule is meant to prompt a measurement rather than to argue about a step.
_is_oversized(instance_type) if {
	is_string(instance_type)
	regex.match(`\.(8|9|12|16|18|24|32|48|56|112)?xlarge$`, instance_type)
	not regex.match(`\.(|2|4)xlarge$`, instance_type)
}

# Metal instances are the whole host by definition.
_is_oversized(instance_type) if {
	is_string(instance_type)
	endswith(instance_type, ".metal")
}

violations contains violation if {
	some res in input.resource
	some res_type in ["aws_instance", "aws_launch_template", "aws_launch_configuration"]
	some name, attrs in res[res_type]
	instance_type := attrs.instance_type
	_is_oversized(instance_type)

	violation := {
		"rule": "oversized_instance_type",
		"severity": "medium",
		"category": "energy",
		"resource_address": sprintf("%v.%v", [res_type, name]),
		"file_path": object.get(attrs, "__tf_file", ""),
		"line_start": object.get(attrs, "__start_line__", null),
		"line_end": object.get(attrs, "__end_line__", null),
		"message": sprintf("'%v.%v' requests %v. Confirm measured usage justifies it — an oversized instance is paid for continuously whether or not the work needs it.", [res_type, name, instance_type]),
	}
}
