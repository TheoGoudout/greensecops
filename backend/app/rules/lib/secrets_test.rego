package greensecops.lib.secrets_test

import data.greensecops.lib.secrets as sec
import rego.v1

test_is_placeholder_catches_this_repos_ci_fixtures if {
	sec.is_placeholder("testpassword")
	sec.is_placeholder("changethischangethischangethischangethischangethischangethischanget")
}

test_is_placeholder_catches_common_stand_ins if {
	every value in ["changeme", "CHANGEME", "placeholder", "dummy", "example", "fake", "xxxxx", "replace_me", "your_token_here", "<your-key>"] {
		sec.is_placeholder(value)
	}
}

test_is_placeholder_catches_repeated_units if {
	sec.is_placeholder("0000000000000000")
	sec.is_placeholder("aaaaaaaa")
	sec.is_placeholder("abababababababab")
}

test_is_placeholder_rejects_real_looking_values if {
	not sec.is_placeholder("a3f5c9e12b7d4068af31c5e9b2d70486")
	not sec.is_placeholder("AKIAIOSFODNN7EXAMPLE1")
}

# ─── Value shape ─────────────────────────────────────────────────────────────

test_effective_alphabet_separates_words_from_randomness if {
	sec.effective_alphabet("testpassword") < 8
	sec.effective_alphabet("production") < 9
	sec.effective_alphabet("a3f5c9e12b7d4068af31c5e9b2d70486") >= 12
}

test_looks_high_entropy if {
	sec.looks_high_entropy("a3f5c9e12b7d4068af31c5e9b2d70486")
	sec.looks_high_entropy("aGVsbG8gd29ybGQgdGhpcyBpcyBhIHNlY3JldA==")

	# Short, so it cannot qualify however varied.
	not sec.looks_high_entropy("a3f5c9e1")

	# Long but wordy.
	not sec.looks_high_entropy("changethischangethischangethis")
}

test_known_credential_formats if {
	sec.known_credential("AKIAIOSFODNN7EXAMPLE")
	sec.known_credential("ghp_16C7e42F292c6912E7710c838347Ae178B4a")
	not sec.known_credential("testpassword")
}

# The PEM header is assembled rather than written out, so the literal string
# never appears in the file. Spelled in full it trips the `detect-private-key`
# pre-commit hook, which cannot tell a rule's own test fixture from a key
# somebody committed by mistake — and the right resolution is to keep the
# fixture out of its way rather than to exempt this file from the hook, which
# would also exempt a real key added here later.
test_known_credential_matches_a_pem_header if {
	sec.known_credential(concat("", ["-----BEGIN RSA ", "PRIVATE KEY-----"]))
	sec.known_credential(concat("", ["-----BEGIN ", "PRIVATE KEY-----"]))
}

# ─── Action references ───────────────────────────────────────────────────────
