# Persistent review state

Media Janitor stores durable review state in SQLite separately from the media library.

The intended layout is:

```text
/media   media dataset
/state   writable persistent application/review state
```

The database path is:

```text
/state/media-janitor.sqlite3
```

Do not put `/state` inside the media root. Identification with persistent state refuses that layout.

## Initialize and inspect state

```bash
media-janitor state-init --state-dir /state
media-janitor state-status --state-dir /state
```

The database stores:

- immutable observation/identification reports;
- staged review proposals;
- proposal decisions;
- audit events.

Reports and staged candidate payloads are stored with SHA-256 digests and verified when loaded.

## Persist an identification run

```bash
media-janitor identify-audiobooks /media \
  --state-dir /state \
  --json /state/latest-identify.json \
  --pretty
```

Supplying `--state-dir` persists the observation report. It does not create review proposals unless explicitly requested.

## Stage strong identity candidates

```bash
media-janitor identify-audiobooks /media \
  --state-dir /state \
  --stage-strong-proposals
```

Only provider results labeled `strong_identity_candidate` are staged automatically, and every staged record starts as `pending`.

Staging does **not** approve candidates, rename/move files, update embedded tags, change Audiobookshelf metadata, generate a filesystem plan, or invoke the writer.

## Review from the CLI

```bash
media-janitor proposal-list --state-dir /state --status pending
```

Record one final decision:

```bash
media-janitor proposal-decide PROPOSAL_ID \
  --state-dir /state \
  --decision approved \
  --note 'Reviewed title, author, narrator, duration, and ASIN'
```

Allowed final decisions are `approved`, `rejected`, and `ignored`.

A final decision is immutable in the current schema. Changed evidence should create a new report/proposal instead of rewriting old review history.

## Review from the local web UI

The same proposals can be reviewed through the built-in web queue:

```bash
media-janitor review-server --state-dir /state
```

Open `http://127.0.0.1:8090`.

The web UI uses the same `StateStore.decide_proposal` path as the CLI, so both interfaces produce the same SQLite status changes and audit events. The UI displays provider/current-server evidence, identity and edition scores, identifiers, warnings, and the candidate digest before presenting approve/reject/ignore actions.

For network access, see [REVIEW_UI.md](REVIEW_UI.md). Non-loopback binding requires a review token and the TrueNAS review container has no media mount.

Most importantly, `approved` still means **approved in review state only**. Neither the CLI nor web UI has a code path to `apply-plan` or to an Audiobookshelf write endpoint.

## Audit trail

```bash
media-janitor audit-list --state-dir /state
```

Or filter one proposal:

```bash
media-janitor audit-list \
  --state-dir /state \
  --entity-type proposal \
  --entity-id PROPOSAL_ID
```

Current audit events include `report_saved`, `proposal_staged`, and `proposal_decided`. Decision events include the candidate digest so the decision remains tied to the exact candidate content that was reviewed.

## SQLite durability choices

The state store currently enables:

- foreign keys;
- WAL journaling;
- a busy timeout for short concurrent access;
- explicit schema-version checking;
- immutable report IDs;
- one proposal per local item per source report;
- content-integrity checks on reports and proposal candidates.

The SQLite database is application/review state, not a replacement for the separate filesystem rollback journal or a TrueNAS/ZFS snapshot.
