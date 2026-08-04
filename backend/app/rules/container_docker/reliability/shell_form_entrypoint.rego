# METADATA
# title: ENTRYPOINT or CMD written in shell form
# description: The final stage declares its entrypoint as a bare string rather than a JSON array, so Docker wraps it in `/bin/sh -c`. The shell becomes PID 1 and the application a child, and a shell in that position does not forward signals — so SIGTERM on `docker stop` never reaches the process. It ignores the graceful-shutdown window entirely and is killed ten seconds later, dropping in-flight requests and skipping whatever cleanup it had.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       FROM node:22-slim
#       COPY . /app
#       CMD node /app/server.js
#     good: |
#       FROM node:22-slim
#       COPY . /app
#       CMD ["node", "/app/server.js"]
#     fix: |
#       Use the JSON array form, which execs the binary directly as PID 1 so it receives signals. If the command genuinely needs shell features such as variable expansion or a pipe, keep the shell but exec the real process at the end of the script, or add a minimal init with the `init` compose option.
package greensecops.container_docker.reliability.shell_form_entrypoint

import rego.v1

# Exec form is a JSON array, so the value starts with `[`. Anything else is
# shell form. Checked on the trimmed value because the parser preserves the
# instruction's argument verbatim.
_is_shell_form(inst) if {
	value := trim_space(inst.value)
	value != ""
	not startswith(value, "[")
}

_final_stage_instructions(df, keyword) := [inst |
	some inst in df.instructions
	inst.instruction == keyword
	inst.stage == df.final_stage
]

violations contains violation if {
	some df in input.dockerfiles
	some keyword in ["ENTRYPOINT", "CMD"]
	instructions := _final_stage_instructions(df, keyword)
	count(instructions) > 0

	# Only the last one of each kind takes effect; an earlier CMD overridden by
	# a later one is not what ships.
	last := instructions[count(instructions) - 1]
	_is_shell_form(last)

	violation := {
		"rule": "shell_form_entrypoint",
		"severity": "medium",
		"category": "reliability",
		"file_path": object.get(df, "__docker_file", ""),
		"line_start": object.get(last, "__start_line__", null),
		"line_end": object.get(last, "__end_line__", null),
		"message": sprintf("%v uses shell form, so /bin/sh becomes PID 1 and never forwards SIGTERM to the application. Use the JSON array form.", [keyword]),
		"context": last.value,
		"discriminator": keyword,
	}
}
