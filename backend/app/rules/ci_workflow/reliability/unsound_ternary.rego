# METADATA
# title: Pseudo-ternary that always takes the same branch
# description: "An expression uses the `condition && A || B` idiom to pick between two values, but `A` is falsy. GitHub expressions have no ternary operator, so this idiom stands in for one — and it only works when the value in the true position is itself truthy. With a falsy `A` the `&&` yields `A`, the `||` then discards it, and `B` is the result whether the condition held or not. The expression looks like a choice and is a constant."
# custom:
#   severity: high
#   severity_weight: 1.5
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         test:
#           runs-on: ubuntu-latest
#           steps:
#             - run: ./test.sh
#               env:
#                 VERBOSE: ${{ github.event_name == 'push' && '' || '--quiet' }}
#     good: |
#       jobs:
#         test:
#           runs-on: ubuntu-latest
#           steps:
#             - run: ./test.sh
#               env:
#                 VERBOSE: ${{ github.event_name == 'push' && '--verbose' || '--quiet' }}
#     fix: |
#       Put a truthy value in the true position. Where the intended value really is empty or zero, the idiom cannot express it — invert the condition so the empty value lands in the `||` position (`${{ cond && 'x' || '' }}` becomes `${{ !cond && '' || 'x' }}` read the other way round), or move the choice out of the expression into an `if:` on two separate steps.
package greensecops.ci_workflow.reliability.unsound_ternary

import data.greensecops.lib.workflow as wf
import rego.v1

# The true arm, written as a literal that GitHub evaluates as false. `''` and
# `""` are the common ones; `0`, `false` and `null` complete the set the
# expression evaluator treats as falsy.
_UNSOUND := `&&\s*(?:''|""|false|null|0)\s*\|\|`

# Only the inside of a `${{ }}` is examined, so a shell `&& false ||` in a run
# script — which is ordinary shell control flow, not a GitHub expression — is
# not reported. `wf.expression_bodies` walks the node for its strings rather
# than marshalling it: `json.marshal` escapes `&` to `\u0026`, which would stop
# this rule's `&&` from ever matching.
_unsound(node) if {
	some body in wf.expression_bodies(node)
	regex.match(_UNSOUND, body)
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	_unsound(step)

	step_label := object.get(step, "name", "unnamed step")
	violation := {
		"rule": "unsound_ternary",
		"severity": "high",
		"category": "reliability",
		"job": job_name,
		"step_index": step_index,
		"message": sprintf("Step '%v' in job '%v' uses the `cond && A || B` idiom with a falsy value in the A position, so the expression yields B regardless of the condition. Put a truthy value in the true position, or invert the condition so the empty value falls to the B side.", [step_label, job_name]),
		"context": "cond && <falsy> || B",
		"discriminator": sprintf("%v:%v", [job_name, step_index]),
	}
}

violations contains violation if {
	some job_name, job in input.jobs
	not _step_level_hit(job)
	_unsound(object.remove(job, ["steps"]))

	violation := {
		"rule": "unsound_ternary",
		"severity": "high",
		"category": "reliability",
		"job": job_name,
		"message": sprintf("Job '%v' uses the `cond && A || B` idiom with a falsy value in the A position, so the expression yields B regardless of the condition. Put a truthy value in the true position, or invert the condition so the empty value falls to the B side.", [job_name]),
		"context": "cond && <falsy> || B",
		"discriminator": sprintf("%v:job", [job_name]),
	}
}

_step_level_hit(job) if {
	some _, step in job.steps
	_unsound(step)
}
