# METADATA
# title: Final stage declares no CMD or ENTRYPOINT
# description: The shipped stage names no default command, so the image runs whatever its base image last declared. That is usually a shell, meaning the container starts, does nothing and exits zero — which reads as success everywhere it is checked. The failure surfaces later as a service that is "running" but never answers, and the base image can change what it inherits at any time.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       FROM python:3.12-slim
#       COPY . /app
#       RUN pip install --no-cache-dir -r /app/requirements.txt
#     good: |
#       FROM python:3.12-slim
#       COPY . /app
#       RUN pip install --no-cache-dir -r /app/requirements.txt
#       CMD ["python", "/app/main.py"]
#     fix: |
#       Declare the command the image is for with CMD or ENTRYPOINT, in JSON array form. Inheriting one from the base image is not the same as declaring it — the base can change it, and nothing in this file records what the image is supposed to run.
package greensecops.container_docker.reliability.missing_cmd_or_entrypoint

import rego.v1

_final_stage(df) := stage if {
	some stage in df.stages
	stage.is_final == true
}

_declares_a_command(df) if {
	some inst in df.instructions
	inst.instruction in {"CMD", "ENTRYPOINT"}
	inst.stage == df.final_stage
}

violations contains violation if {
	some df in input.dockerfiles
	stage := _final_stage(df)
	not _declares_a_command(df)

	violation := {
		"rule": "missing_cmd_or_entrypoint",
		"severity": "medium",
		"category": "reliability",
		"file_path": object.get(df, "__docker_file", ""),
		"stage_name": object.get(stage, "name", null),
		"line_start": object.get(stage, "__start_line__", null),
		"line_end": object.get(stage, "__end_line__", null),
		"message": "The final stage declares no CMD or ENTRYPOINT, so the image runs whatever its base image last set — usually a shell that exits immediately and reads as success. Declare the command explicitly.",
	}
}
