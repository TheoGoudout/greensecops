# Value-shape helpers for deciding whether a *literal* looks like a real
# credential. Extracted from `lib/workflow.rego` because the question is not
# specific to GitHub Actions: `container_docker`'s `compose_hardcoded_secret`
# asked it too, and answered it with "the variable is named like a secret and
# the value is non-empty" — which reported `POSTGRES_PASSWORD: changethis` in a
# development Compose file as a leaked credential, at high severity, with a fix
# that breaks the stack.
#
# Like `lib/workflow.rego` this carries no METADATA and emits no `violations`;
# `rego_metadata.iter_rule_files` skips everything under `lib/`.
package greensecops.lib.secrets

import rego.v1

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
