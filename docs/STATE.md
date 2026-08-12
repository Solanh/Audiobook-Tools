# Persistent review state

Media Janitor stores durable review state in SQLite separately from the media library.

For the TrueNAS Compose example, the intended layout is:

```text
/media   read-only during observation/review
/state   writable persistent application state
```

The database path is:

```text
/state/media-janitor.sqlite3
```

Do not put the state directory inside the media root. `identify-audiobooks --state-dir ...` refuses that layout.

## Initialize and inspect state

```bash
media-janitor state-init --state-dir /state
media-janitor state-status --state-dir /state
```

The database currently stores:

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

## Stage strong identity candidates for review

```bash
media-janitor identify-audiobooks /media \
  --state-dir /state \
  --stage-strong-proposals
```

Only provider results labeled `strong_identity_candidate` are staged automatically, and every staged record starts with status `pending`.

Staging does **not**:

- approve the candidate;
- rename or move files;
- update embedded tags;
- change Audiobookshelf metadata;
- generate a filesystem plan;
- invoke the writer container.

The proposal stores the selected provider candidate plus the full provider/current-server evidence that led to it.

## Review proposals

```bash
media-janitor proposal-list --state-dir /state --status pending
```

For machine-readable output:

```bash
media-janitor proposal-list \
  --state-dir /state \
  --status pending \
  --json /state/pending-proposals.json \
  --pretty
```

## Record a decision

```bash
media-janitor proposal-decide PROPOSAL_ID \
  --state-dir /state \
  --decision approved \
  --note 'Reviewed title, author, narrator, duration, and ASIN'
```

Allowed final decisions are:

- `approved`
- `rejected`
- `ignored`

A final decision is immutable in the current schema. If the evidence later changes, a future identification report should create a new proposal rather than silently rewriting the history of the old one.

Most importantly, `approved` currently means **approved in review state only**. There is intentionally no code path from `proposal-decide` to `apply-plan` or to an Audiobookshelf write endpoint yet.

That bridge should only be added after reviewed proposal-to-plan generation has its own stale-source checks and verification tests.

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

Current audit events include:

- `report_saved`
- `proposal_staged`
- `proposal_decided`

Decision events include the candidate digest so the decision remains tied to the candidate content that was reviewed.

## SQLite durability choices

The state store currently enables:

- foreign keys;
- WAL journaling;
- a busy timeout for short concurrent access;
- explicit schema-version checking;
- immutable report IDs;
- one proposal per local item per source report;
- content integrity checks on reports and proposal candidates.

The SQLite database is application/review state, not a replacement for the separate filesystem rollback journal or a TrueNAS/ZFS snapshot.
