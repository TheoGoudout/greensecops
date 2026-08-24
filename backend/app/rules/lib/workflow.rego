# Shared helpers for the ci_workflow rules.
#
# This package carries no METADATA and emits no `violations` — it is not a rule,
# and `rego_metadata.iter_rule_files` skips everything under `lib/` for that
# reason. It ships inside `rules/` anyway because `opa/Dockerfile` copies exactly
# that directory to `/policies`, so a helper package anywhere else would not
# resolve for the rules that import it.
#
# Everything here was extracted from a rule that already had it, usually from
# whichever copy was the most careful. Where two rules disagreed, the stricter
# reading won and the loose one is being fixed to match — `_is_secret_ref` was
# defined twice with different semantics (`hardcoded_secrets` tested two literal
# prefixes, `hardcoded_env_values` tested one), and both were wrong in ways that
# produced false positives on this repository's own workflows.
package greensecops.lib.workflow

import rego.v1

# ─── Expressions ─────────────────────────────────────────────────────────────

# True when `value` contains a `${{ ... }}` expression anywhere, not only at
# position 0. The anchored `startswith` this replaces missed
# `Bearer ${{ secrets.TOKEN }}` and `https://x@${{ secrets.HOST }}`, both of
# which are secret references and neither of which starts with the delimiter.
is_expression(value) if {
	is_string(value)
	regex.match(`\$\{\{.*\}\}`, value)
}

# True when `value` references a secret. Whitespace-tolerant, so `${{secrets.X}}`
# counts — the two-prefix `startswith(value, "${{ secrets.")` test it replaces
# treated that as a hardcoded literal.
references_secret(value) if {
	is_string(value)
	regex.match(`\$\{\{\s*secrets\.[A-Za-z0-9_-]+\s*\}\}`, value)
}

# True when `value` references a repository or environment variable.
references_var(value) if {
	is_string(value)
	regex.match(`\$\{\{\s*vars\.[A-Za-z0-9_-]+\s*\}\}`, value)
}

# Every string anywhere inside `node`, at any depth. Rules that ask "does this
# step mention X anywhere" reached for `json.marshal` before this existed, which
# is wrong twice over: Go's marshaller HTML-escapes `&`, `<` and `>`, so a
# pattern containing `&&` silently never matched a marshalled document, and the
# JSON punctuation between values can let a pattern span two unrelated fields.
# `walk` has neither problem — it yields the values themselves.
strings_within(node) := {value |
	walk(node, [_, value])
	is_string(value)
}

# The bodies of every `${{ ... }}` in `node`, as written. Checking these rather
# than the raw text is what keeps expression rules off shell syntax that merely
# looks similar — `test -f x && false || echo` in a `run:` script is control
# flow, not a GitHub expression.
expression_bodies(node) := {body |
	some text in strings_within(node)
	some body in regex.find_n(`\$\{\{[^}]*\}\}`, text, -1)
}

# ─── Value shape ─────────────────────────────────────────────────────────────

# Obvious non-secrets that happen to sit under a secret-shaped name. CI fixtures
# for throwaway containers are the overwhelming case: a Postgres that lives for
# the length of one job is seeded with `testpassword`, and reporting that as a
# leaked credential — at critical, with a fix that replaces it with an undefined
# `${{ secrets.* }}` and breaks the job — is worse than reporting nothing.
_placeholder_pattern := `(?i)^(changeme|change_this|changethis|placeholder|example|sample|dummy|fake|test|testing|secret|password|passwd|token|foo|bar|baz|xxx+|none|null|nil|undefined|unset|replace_?me|your_?[a-z_]*_?here|<[^>]+>)[-_]?[a-z0-9_-]*$`

is_placeholder(value) if {
	is_string(value)
	regex.match(_placeholder_pattern, value)
}

# A value made of one short unit repeated to length — `changethischangethis...`,
# `0000000000`, `aaaaaaaa`. Length-based tests pass these because they are long;
# they are not secrets, they are someone holding down a key. RE2 has no
# backreferences, so this is done by chunking rather than by `^(.+?)\1+$`.
is_placeholder(value) if {
	is_string(value)
	total := count(value)
	total >= 8
	some unit_len in numbers.range(1, 12)
	unit_len < total
	total % unit_len == 0
	chunks := [substring(value, i, unit_len) |
		some i in numbers.range_step(0, total - unit_len, unit_len)
	]
	count({c | some c in chunks}) == 1
}

# Credential formats worth reporting on sight, whatever the variable is called
# and whatever its entropy. Format beats heuristics: `AKIA` + 16 uppercase
# alphanumerics is an AWS access key ID and nothing else.
known_credential(value) if {
	is_string(value)
	some pattern in [
		`AKIA[0-9A-Z]{16}`, # AWS access key ID
		`ASIA[0-9A-Z]{16}`, # AWS temporary access key ID
		`gh[pousr]_[A-Za-z0-9]{36,}`, # GitHub PAT / OAuth / user / server / refresh
		`github_pat_[A-Za-z0-9_]{22,}`, # GitHub fine-grained PAT
		`sk-[A-Za-z0-9]{20,}`, # OpenAI-style secret key
		`xox[baprs]-[A-Za-z0-9-]{10,}`, # Slack token
		`AIza[0-9A-Za-z_-]{35}`, # Google API key
		`-----BEGIN [A-Z ]*PRIVATE KEY-----`, # PEM private key
		`eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.`, # JWT
	]
	regex.match(pattern, value)
}

# How many distinct symbols the value behaves as if it were drawn from — the
# inverse Simpson index, 1 / Σp². Shannon entropy would be the textbook measure,
# but OPA ships no logarithm builtin (no `log`, no `pow`, no `sqrt`), so bits per
# character is not expressible. This is: it needs only sums and a division, and
# it answers the same question. For a value drawn uniformly from k symbols it
# returns k, so the threshold below reads directly as "an alphabet at least this
# wide".
#
# Measured on the values this repository's own workflows actually contain:
#   "testpassword"      ->  7.2   (12 chars, 9 distinct, heavily repeated)
#   "production"        ->  8.3
#   "changethis" x6.7   ->  8.4   (the SECRET_KEY fixture; also a repeated unit)
#   32 chars of hex     -> 16.0
#   40 chars of base64  -> 20.0
effective_alphabet(value) := k if {
	is_string(value)
	chars := split(value, "")
	total := count(chars)
	total > 0
	counts := {c: n | some c in chars; n := count([x | some x in chars; x == c])}
	sum_squares := sum([p_squared |
		some _, n in counts
		p_squared := (n * n) / (total * total)
	])
	sum_squares > 0
	k := 1 / sum_squares
}

# Long enough and varied enough to be a real credential rather than a word or a
# CI fixture. The corpus had no value-shape check at all before this, which is
# why every rule that wanted "does this look like a secret" had to settle for
# "is it named like one".
looks_high_entropy(value) if {
	is_string(value)
	count(value) >= 16
	effective_alphabet(value) >= 12
}

# ─── Action references ───────────────────────────────────────────────────────

# `owner/repo` from a `uses:` value, dropping any `@ref` and any subpath.
action_name(uses) := split(uses, "@")[0] if is_string(uses)

# The `@ref` half of a `uses:` value; undefined when there is none, so callers
# get a failed body rather than a bogus empty ref.
action_ref(uses) := ref if {
	is_string(uses)
	parts := split(uses, "@")
	count(parts) > 1
	ref := parts[1]
}

is_sha_pin(uses) if regex.match(`^[0-9a-f]{40}$`, action_ref(uses))

# A local reusable workflow (`./.github/workflows/x.yml`) or a Docker action.
# Neither is pinnable the way a published action is, so pinning rules must skip
# them rather than reporting an unfixable finding.
is_local_ref(uses) if {
	is_string(uses)
	startswith(uses, "./")
}

is_docker_ref(uses) if {
	is_string(uses)
	startswith(uses, "docker://")
}

# ─── Triggers ────────────────────────────────────────────────────────────────

# The set of trigger names, normalised across the three shapes `on:` can take:
# a bare string (`on: push`), a list (`on: [push, pull_request]`) and a mapping
# (`on: {push: {...}}`). Six rules each carried their own four-clause version of
# this; they disagreed, and the list form was untested in every one of them.
trigger_names := {name | some name, _ in input.on} if is_object(input.on)

trigger_names := {name | some name in input.on} if is_array(input.on)

trigger_names := {input.on} if is_string(input.on)

has_trigger(name) if name in trigger_names

# Triggers that run with a token in a context an outside contributor can reach.
runs_on_untrusted_input if {
	some trigger in ["pull_request_target", "issue_comment", "workflow_run"]
	has_trigger(trigger)
}

# ─── Jobs ────────────────────────────────────────────────────────────────────

# A job that calls a reusable workflow rather than running steps. GitHub rejects
# most job-level keys on these — `timeout-minutes` and `runs-on` among them — so
# a rule demanding one is asking for something the author cannot write.
is_reusable_call(job) if {
	is_string(job.uses)
	not job.steps
}

# `needs:` normalised across the scalar and list forms.
job_needs(job) := {job.needs} if is_string(job.needs)

job_needs(job) := {n | some n in job.needs} if is_array(job.needs)

# True when any job in the workflow reads an output of `job_name`, either
# through `needs.<job>.outputs.*` in an expression or by declaring outputs that
# reference it. This is what separates a `needs:` edge that carries data from
# one that only orders work.
job_outputs_consumed(job_name) if {
	some _, job in input.jobs
	regex.match(sprintf(`needs\.%v\.outputs\.`, [regex.replace(job_name, `[.*+?^${}()|\[\]\\]`, `\\$0`)]), json.marshal(job))
}
