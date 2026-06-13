# Checkpoint: B2 push diagnostic logging (v0.5.2)

Read `CLAUDE.md` first. This is a diagnostic-only pass: add logging, change no
behaviour. Stop and report.

## Why

The B2 upload fails on every run with `AccessDenied: not entitled` (403),
including after a clean restart that loaded current options (the v0.5.1 startup
banner is present in the log immediately before the failure). "Not entitled"
means a valid key authenticated but lacks write rights, yet the configured key
(`...004`) has `writeFiles` scoped to the bucket. We need to see exactly what the
add-on sends to B2 to localise this: which key, how the remote is built, and
whether a stale rclone config is being reused.

## Add logging (no behaviour change)

At the point in `archive.py` where the B2 destination is resolved and the rclone
copyto is built and run, add INFO logging:

1. The B2 parameters read from options at archive time: `b2_key_id` (full, the
   keyID is not a secret), `b2_bucket`, `b2_endpoint`, and the destination object
   path actually used.
2. A safe fingerprint of the secret that does NOT reveal it: its length, first 4
   and last 2 characters, and whether it has leading or trailing whitespace, for
   example `b2_key: len=31 head=K004 tail=8o ws=no`. A length or whitespace
   anomaly would point to a copy-paste corruption.
3. The exact rclone invocation used for the B2 copyto with the secret REDACTED:
   the full argument list or connection string, secret replaced with `****`. It
   must show the provider, endpoint, bucket, access_key_id and path actually
   passed to rclone.
4. If the code uses an rclone config FILE (for example under `/data`) rather than
   inline connection strings: log its path, whether it already existed at the
   start of this run (reused) or was written this run, and the redacted S3/`[b2]`
   section it contains with the secret masked. If it uses inline connection
   strings, log that fact (redacted). This directly tests whether a stale config
   baked from an earlier key is being reused across restarts.

## Hard constraints

- NEVER log the `b2_key` secret or `nas_password` in plaintext anywhere. Redact to
  `****`. The keyID, bucket, endpoint and path are fine to log in full.
- No change to upload, verification, path-building, the key, or any other
  behaviour. Logging only.

## Scope

`archive.py`, plus the options-reading path if the B2 values are read elsewhere.
Add a small redaction helper if useful. Bump version to 0.5.2 and note it in
`CHANGELOG.md` and `DOCS.md` as a diagnostic-logging release.

## Tests

One test that the redaction helper masks the secret and that the fingerprint
string can never contain the full secret. Otherwise keep it minimal. ruff clean
and mypy strict clean on changed code.

## Stop and report

The usual seven points. In particular, state exactly which strings get logged and
confirm the secret cannot appear in plaintext in any of them.
