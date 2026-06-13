# Checkpoint: Fix NAS verification and simulation InfluxDB reads (v0.5.1)

Read `CLAUDE.md` first. This file is the contract for this increment. It is a
bugfix pass. Stop and report at the end.

## Context

Two defects surfaced in a live run on Bluey (logs below). Neither is a
credential problem; the SMB login now succeeds and the file uploads. Fix both.

## Defect 1: single-file backup verification fails ("is a file not a directory")

Observed:

```
ERROR rclone check failed: Failed to create file system for
"nas:energy-archive//2026/06/energy_5min_2026-06-12.parquet": is a file not a directory
ERROR Checksum verification failed for nas:energy-archive//2026/06/energy_5min_2026-06-12.parquet
```

The upload itself succeeds (rclone reports the path as an existing file). The
verification step is wrong: it points `rclone check` at the full remote file path
as if it were a filesystem root, and `rclone check` operates on directories, not
file paths, so SMB rejects it.

Also note the double slash `energy-archive//2026`: with `nas_path` set empty, the
remote path is being joined as share + "" + "/2026/06", producing `//`.

Required fixes:

1. Verify the single uploaded file correctly, in a way that works for BOTH
   backends. SMB has no server-side checksum, so a hash comparison there needs
   `--download`; S3/B2 exposes a hash natively. Choose a method that succeeds on
   both, for example checking the parent directory restricted to the one file
   (`--files-from` or `--include`) with `--download`, or an explicit hashsum
   comparison, rather than pointing `rclone check` at the file path. Do not let a
   correct, present, matching file report as a verification failure.
2. Normalise the remote path construction so an empty `nas_path` does not produce
   a double slash. Empty path should yield `energy-archive/2026/06/...`, not
   `energy-archive//2026/06/...`.
3. The per-destination health timestamp (`backup_nas_last_success`,
   `backup_cloud_last_success`) must update only on a genuinely successful and
   verified push, and the existing "one destination failing does not stop the
   other" behaviour must be preserved.

Apply the same verification correction to both the SMB and the S3 destinations,
since they share the verification path. Note: B2 currently fails earlier at the
upload step on a credentials issue (AccessDenied 403) that the user is fixing
separately; do not attempt to fix B2 credentials here, but ensure the verification
logic is correct for when the upload succeeds.

## Defect 2: simulation InfluxDB reads fail on string fields

Observed:

```
WARNING InfluxDB mean failed (sensor.goodwe_pv_power_total):
  mean: unsupported aggregate column type string
WARNING InfluxDB profile failed (sensor.goodwe_house_consumption):
  unsupported input type for mean aggregate: string
```

Effect: the simulation runs on `solar=0W load=0W` and a broken reserve profile,
because these reads error out instead of returning data.

Cause: the simulation's InfluxDB queries in `sources.py` (the previous-period
actuals read and the trailing 7-day load/solar profile read) aggregate without
filtering to the numeric value field. HA logs multiple fields per entity, the
numeric state under `_field == "value"` plus string attribute fields (the `_str`
ones), so `mean()` hits a string column and fails.

Required fix:

- In `sources.py`, every read that aggregates a sensor must filter
  `_field == "value"` before `mean()` (or `aggregateWindow(fn: mean)`), so only
  the numeric value column is aggregated.
- The daily archive's reads already work (it wrote 25 columns with no such
  error), so this is the simulation read path specifically. Confirm the archive's
  reads already filter `_field == "value"` and leave them unchanged; only fix the
  simulation reads.

## In scope

- `app/sources.py`: add the `_field == "value"` filter to the simulation reads.
- `app/archive.py`: fix the single-file verification and the empty-`nas_path`
  double-slash.
- `tests/`: cover both fixes.
- Bump the patch version to 0.5.1; update `DOCS.md` and `CHANGELOG.md`.

## Out of scope

B2 credentials (user-side). The daily timer, the button, the simulation logic,
and any new features. Do not change the archive's variable selection or rollup
rules.

## Constraints

No secrets. Australian English, no em dashes. Follow `CLAUDE.md`.

## Acceptance criteria

- pytest green, including new tests: the simulation read queries include the
  `_field == "value"` filter (mock the client and assert string fields are
  excluded, or assert the query text contains the filter); the remote path
  builder produces no double slash when `nas_path` is empty; the verification
  invocation targets a directory-plus-file form, not a bare file path.
- ruff clean and mypy strict clean on the changed files.
- On Bluey after deploy: no "mean: unsupported aggregate column type string"
  warnings; the simulation logs real non-zero solar and load when the inverter is
  producing and consuming; the NAS verification succeeds against the uploaded file
  and `backup_nas_last_success` updates; the remote path has no double slash.

## Stop and report

1. Summary of what was built.
2. Files changed.
3. Decisions and assumptions made (the verification method chosen for single
   files across both backends; how the path is normalised). Log them.
4. How it was verified (tests; note that live B2 verification still awaits the
   user's key fix).
5. Open questions.
6. Risks and limitations.
7. Recommended next step.
