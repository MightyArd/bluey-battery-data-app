# Checkpoint: B2 no_check_bucket fix (v0.5.3)

Read `CLAUDE.md` first. Small targeted fix. Stop and report.

## Diagnosis (from the v0.5.2 logs)

The B2 diagnostic confirmed the add-on sends correct credentials and a correct
request: `key_id=...004`, secret fingerprint `len=31 head=K004 tail=8o ws=no`
(matches the intended key, uncorrupted), `bucket=bluey-energy-archive`,
`endpoint=s3.us-west-004.backblazeb2.com`, config freshly written from current
options. Yet B2 returns `403 AccessDenied: not entitled` at "failed to prepare
upload".

This exonerates the credentials. The cause is rclone's S3 backend performing a
bucket existence/creation check before the upload. The B2 application key is
restricted to a single bucket and has no bucket-create or list-all-buckets
entitlement, so that check returns "not entitled". The SMB (NAS) backend has no
bucket concept, which is why the NAS leg succeeds and only B2 fails, and why every
bucket-restricted key tried so far failed identically.

rclone's documented remedy is `no_check_bucket = true` ("needed if the user you
are using does not have bucket creation permissions").

## Change

In `write_rclone_config`, add `no_check_bucket = true` to the `[b2]` S3 remote
section only. (Equivalent to `--s3-no-check-bucket` on the copyto, but the
config-level setting is cleaner and will show in the diagnostic dump.) Leave the
`[nas]` remote untouched. No other behaviour changes.

Keep the v0.5.2 diagnostic logging in place for this run, so the config dump will
show `no_check_bucket = true` under `[b2]` and we can confirm the upload now
succeeds. A later patch can trim the diagnostics once B2 is green.

## Scope

`app/archive.py` (`write_rclone_config`). Version to 0.5.3 in `config.yaml`,
`app/main.py`, `app/publisher.py`. `CHANGELOG.md`, `DOCS.md`.

## Tests

Assert the generated `[b2]` section contains `no_check_bucket = true` and the
`[nas]` section does not. Keep minimal. ruff clean, mypy strict clean on changed
code.

## Acceptance criteria

On Bluey after deploy: the B2 diagnostic config dump shows `no_check_bucket = true`
under `[b2]`; the B2 copyto succeeds; `Pushed and verified` appears for the cloud
leg; the `dest=cloud` backup-health timestamp updates.

## Stop and report

The usual seven points.
