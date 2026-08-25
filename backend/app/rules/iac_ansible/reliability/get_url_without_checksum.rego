# METADATA
# title: Download with no checksum
# description: A get_url task with no checksum accepts whatever the remote serves. The file is not verified, a truncated or replaced download installs silently, and the module cannot skip the transfer when the correct file is already in place.
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       - name: Install the compose plugin
#         ansible.builtin.get_url:
#           url: https://example.com/docker-compose
#           dest: /usr/libexec/docker/cli-plugins/docker-compose
#           mode: "0755"
#     good: |
#       - name: Install the compose plugin
#         ansible.builtin.get_url:
#           url: https://example.com/docker-compose
#           dest: /usr/libexec/docker/cli-plugins/docker-compose
#           mode: "0755"
#           checksum: "sha256:{{ compose_sha256 }}"
#     fix: |
#       Add checksum: in "sha256:<digest>" form. Where the URL is templated per version or architecture, key a variable map on the same value the URL uses.
package greensecops.iac_ansible.reliability.get_url_without_checksum

import data.greensecops.lib.ansible as ans
import rego.v1

violations contains violation if {
	some f in input.files
	some task in ans.tasks_of(f)
	ans.module(task) == "ansible.builtin.get_url"
	not ans.has_arg(task, "checksum")
	violation := {
		"rule": "get_url_without_checksum",
		"severity": "high",
		"category": "reliability",
		"file_path": ans.path(f),
		"line_start": ans.line(task),
		"line_end": ans.end_line(task),
		"task_name": ans.name_of(task),
		"discriminator": ans.discriminator(task),
		"message": sprintf("Task '%v' downloads a file with no checksum — nothing verifies what the remote served.", [ans.name_of(task)]),
	}
}
