package greensecops.container_docker.maintainability.missing_workdir_test

import data.greensecops.container_docker.maintainability.missing_workdir
import rego.v1

_stage(index, name, final) := {
	"index": index,
	"name": name,
	"is_final": final,
	"__start_line__": 1,
	"__end_line__": 9,
}

_df(stages, instructions) := {"dockerfiles": [{
	"__docker_file": "Dockerfile",
	"final_stage": stages[count(stages) - 1].index,
	"stages": stages,
	"instructions": instructions,
}]}

_inst(keyword, value, stage) := {
	"instruction": keyword,
	"value": value,
	"flags": {},
	"stage": stage,
	"heredoc": null,
	"__start_line__": 3,
	"__end_line__": 3,
}

test_violation_when_no_workdir_is_set if {
	violations := missing_workdir.violations with input as _df(
		[_stage(0, null, true)],
		[
			_inst("COPY", ". /app", 0),
			_inst("CMD", "[\"node\", \"server.js\"]", 0),
		],
	)
	count(violations) == 1
}

test_no_violation_when_workdir_is_set if {
	violations := missing_workdir.violations with input as _df(
		[_stage(0, null, true)],
		[
			_inst("WORKDIR", "/app", 0),
			_inst("COPY", ". .", 0),
			_inst("CMD", "[\"node\", \"server.js\"]", 0),
		],
	)
	count(violations) == 0
}

# A WORKDIR in a builder stage does not carry into the final stage.
test_violation_when_only_a_builder_stage_sets_workdir if {
	violations := missing_workdir.violations with input as _df(
		[_stage(0, "builder", false), _stage(1, null, true)],
		[
			_inst("WORKDIR", "/build", 0),
			_inst("COPY", "--from=builder /build/out app/", 1),
		],
	)
	count(violations) == 1
}

# The nginx/distroless shape: a file tree copied to an absolute destination and
# a command the base image supplies. Nothing resolves against a working
# directory, so there is nothing to state. This fired on four of this
# repository's own Dockerfiles.
test_no_violation_when_every_path_is_absolute if {
	violations := missing_workdir.violations with input as _df(
		[_stage(0, "builder", false), _stage(1, null, true)],
		[
			_inst("COPY", "--from=builder /build/html /usr/share/nginx/html", 1),
			_inst("USER", "101", 1),
		],
	)
	count(violations) == 0
}

test_violation_when_a_run_step_changes_directory if {
	violations := missing_workdir.violations with input as _df(
		[_stage(0, null, true)],
		[_inst("RUN", "cd src && make", 0)],
	)
	count(violations) == 1
}

# A scratch/distroless final stage that only receives a file tree has no
# relative paths to resolve.
test_no_violation_for_a_stage_with_no_work if {
	violations := missing_workdir.violations with input as _df(
		[_stage(0, "builder", false), _stage(1, null, true)],
		[
			_inst("RUN", "go build -o /out/app", 0),
			_inst("USER", "10001", 1),
		],
	)
	count(violations) == 0
}

test_reports_the_final_stage_name if {
	violations := missing_workdir.violations with input as _df(
		[_stage(0, "runtime", true)],
		[_inst("RUN", "./configure", 0)],
	)
	count(violations) == 1
	some v in violations
	v.stage_name == "runtime"
}

test_one_finding_per_dockerfile if {
	violations := missing_workdir.violations with input as _df(
		[_stage(0, null, true)],
		[
			_inst("RUN", "npm ci", 0),
			_inst("COPY", ". /app", 0),
			_inst("CMD", "[\"node\", \"server.js\"]", 0),
		],
	)
	count(violations) == 1
}
