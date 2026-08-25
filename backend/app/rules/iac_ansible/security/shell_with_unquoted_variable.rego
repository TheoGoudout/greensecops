# METADATA
# title: Unquoted variable in a shell command
# description: A shell or command task interpolates a Jinja expression straight into a command line with no quote filter, so whatever the variable resolves to is re-parsed by the shell. A value containing a space, a semicolon or a backtick changes what runs.
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       - name: Log in to the registry
#         ansible.builtin.shell:
#           cmd: docker login --password-stdin {{ registry_host }}
#     good: |
#       - name: Log in to the registry
#         ansible.builtin.shell:
#           cmd: docker login --password-stdin {{ registry_host | quote }}
#     fix: |
#       Apply the quote filter to every interpolated expression, or move to ansible.builtin.command with an argv list, which is not shell-interpreted at all.
package greensecops.iac_ansible.security.shell_with_unquoted_variable

import data.greensecops.lib.ansible as ans
import rego.v1

_expressions(command) := regex.find_n(`\{\{[^}]*\}\}`, command, -1)

# Whitespace-normalised so `| quote` and `|quote` read alike.
_quoted(expression) if contains(replace(expression, " ", ""), "|quote")

violations contains violation if {
	some f in input.files
	some task in ans.tasks_of(f)
	ans.is_command(task)

	# Only a free-form command line is shell-interpreted. An `argv` list is
	# passed to execve as-is, which is why this rule must not report it.
	command := ans.command_string(task)
	is_string(command)
	unquoted := {expression |
		some expression in _expressions(command)
		not _quoted(expression)
	}
	count(unquoted) > 0
	violation := {
		"rule": "shell_with_unquoted_variable",
		"severity": "high",
		"category": "security",
		"file_path": ans.path(f),
		"line_start": ans.line(task),
		"line_end": ans.end_line(task),
		"task_name": ans.name_of(task),
		"context": concat(", ", sort(unquoted)),
		"discriminator": ans.discriminator(task),
		"message": sprintf("Task '%v' interpolates %v into a shell command with no quote filter.", [ans.name_of(task), concat(", ", sort(unquoted))]),
	}
}
