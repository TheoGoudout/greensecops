package greensecops.lib.workflow_test

import data.greensecops.lib.workflow as wf
import rego.v1

# ─── Expressions ─────────────────────────────────────────────────────────────

test_references_secret_tolerates_whitespace if {
	wf.references_secret("${{ secrets.TOKEN }}")
	wf.references_secret("${{secrets.TOKEN}}")
	wf.references_secret("${{   secrets.TOKEN   }}")
}

# The `startswith(value, "${{ secrets.")` test this replaces missed both of
# these, and both are secret references.
test_references_secret_when_not_at_position_zero if {
	wf.references_secret("Bearer ${{ secrets.TOKEN }}")
	wf.references_secret("https://x@${{ secrets.HOST }}/path")
}

test_references_secret_rejects_non_secrets if {
	not wf.references_secret("${{ vars.PUBLIC_URL }}")
	not wf.references_secret("${{ github.token }}")
	not wf.references_secret("plain-literal")
}

test_is_expression_covers_any_context if {
	wf.is_expression("${{ github.token }}")
	wf.is_expression("${{ inputs.environment }}")
	wf.is_expression("prefix-${{ env.FOO }}-suffix")
	not wf.is_expression("no expression here")
}

test_references_var if {
	wf.references_var("${{ vars.API_URL }}")
	not wf.references_var("${{ secrets.API_URL }}")
}

# ─── Placeholders ────────────────────────────────────────────────────────────

# These two are the exact values in this repository's test-backend,
# test-docker-compose and playwright workflows that were reported as critical
# hardcoded secrets.
test_action_name_and_ref if {
	wf.action_name("actions/checkout@v4") == "actions/checkout"
	wf.action_ref("actions/checkout@v4") == "v4"

	# Subpaths keep their repo prefix, which is what pinning rules key on.
	wf.action_name("github/codeql-action/upload-sarif@v3") == "github/codeql-action/upload-sarif"
}

test_action_ref_undefined_without_a_ref if {
	not wf.action_ref("actions/checkout")
}

test_is_sha_pin if {
	wf.is_sha_pin("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1")
	not wf.is_sha_pin("actions/checkout@v4")
	not wf.is_sha_pin("actions/checkout@main")
}

test_local_and_docker_refs if {
	wf.is_local_ref("./.github/workflows/deploy-reusable.yml")
	wf.is_docker_ref("docker://alpine:3.20")
	not wf.is_local_ref("actions/checkout@v4")
}

# ─── Triggers ────────────────────────────────────────────────────────────────

test_trigger_names_mapping_form if {
	names := wf.trigger_names with input as {"on": {"push": {"branches": ["main"]}, "pull_request": null}}
	names == {"push", "pull_request"}
}

# The list form was untested in all six rules that hand-rolled this.
test_trigger_names_list_form if {
	names := wf.trigger_names with input as {"on": ["push", "pull_request"]}
	names == {"push", "pull_request"}
}

test_trigger_names_string_form if {
	names := wf.trigger_names with input as {"on": "push"}
	names == {"push"}
}

test_has_trigger if {
	wf.has_trigger("pull_request") with input as {"on": ["push", "pull_request"]}
	not wf.has_trigger("schedule") with input as {"on": ["push", "pull_request"]}
}

test_runs_on_untrusted_input if {
	wf.runs_on_untrusted_input with input as {"on": {"pull_request_target": null}}
	wf.runs_on_untrusted_input with input as {"on": ["workflow_run"]}
	not wf.runs_on_untrusted_input with input as {"on": {"pull_request": null}}
}

# ─── Jobs ────────────────────────────────────────────────────────────────────

# GitHub rejects `timeout-minutes` on a job that calls a reusable workflow, so
# `missing_timeout` has to be able to tell one apart.
test_is_reusable_call if {
	wf.is_reusable_call({"uses": "./.github/workflows/deploy-reusable.yml", "with": {"environment": "staging"}})
	not wf.is_reusable_call({"runs-on": "ubuntu-latest", "steps": [{"run": "make"}]})
}

test_job_needs_both_forms if {
	wf.job_needs({"needs": "build"}) == {"build"}
	wf.job_needs({"needs": ["build", "lint"]}) == {"build", "lint"}
}

test_job_outputs_consumed if {
	consumed := {"jobs": {
		"build": {"outputs": {"tag": "${{ steps.x.outputs.tag }}"}},
		"deploy": {"needs": "build", "steps": [{"run": "deploy ${{ needs.build.outputs.tag }}"}]},
	}}
	wf.job_outputs_consumed("build") with input as consumed
}

test_job_outputs_not_consumed_when_needs_only_orders if {
	ordered := {"jobs": {
		"lint": {"steps": [{"run": "lint"}]},
		"test": {"needs": "lint", "steps": [{"run": "pytest"}]},
	}}
	not wf.job_outputs_consumed("lint") with input as ordered
}
