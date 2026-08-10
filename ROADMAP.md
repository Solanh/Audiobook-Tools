# Media Janitor Roadmap

This repository is evolving from two one-off audiobook renaming scripts into a personal, self-hosted media cleanup toolkit for a TrueNAS library. Audiobooks remain the first target, with Jellyfin movie/TV cleanup sharing the same scan, context, planning, review, and reversible filesystem-operation core.

## Primary goal

Point the tool at a messy media dataset, let it understand the surrounding directory context, propose a clean canonical structure and metadata, review uncertain cases, and apply only approved changes with a durable rollback journal.

The local LLM is a context interpreter, not an authority. It may parse names, infer grouping, and rank candidates, but it never directly mutates files or server metadata.

## Core workflow

```text
SCAN (read only)
  -> SNAPSHOT
  -> ANALYZE (rules + tags + server metadata + optional local LLM)
  -> IDENTIFY (provider candidates + evidence)
  -> PLAN (explicit reversible operations + source fingerprints)
  -> REVIEW
  -> SNAPSHOT/BACKUP CHECK
  -> APPLY (durable journal)
  -> VERIFY
  -> RESCAN AUDIOBOOKSHELF/JELLYFIN
       \
        -> ROLLBACK from journal if needed
```

## Architecture map

```text
media_janitor/
  scanner.py          filesystem inventory and directory context
  models.py           snapshots, versioned plans, reversible operations
  audiobook.py        deterministic audiobook filename/chapter parsing
  journal.py          durable atomic apply/rollback journal
  executor.py         guarded filesystem apply + rollback
  cli.py              scan/analyze/validate/apply/rollback commands

  adapters/           planned
    audiobookshelf    current metadata, provider search, approved updates, rescan
    jellyfin          identity/metadata, refresh integration

  llm/                planned
    ollama             local structured context interpretation
    schemas            strict validated output

  web/                planned
    review queue       current vs proposed state, evidence, approve/edit/reject
```

The implementation can stay relatively flat until these pieces become large enough to justify deeper subpackages.

## Safety invariants

These are architectural requirements, not optional polish:

1. Scanning and analysis never mutate media.
2. A model/provider response never directly becomes a filesystem operation.
3. Every write comes from an explicit versioned plan.
4. Plans used for filesystem apply must be fully reversible.
5. The rollback journal is persisted outside the media root before the first write.
6. Journal updates are written atomically and fsynced.
7. Interrupted `applying`/`rolling_back` states must be reconcilable from filesystem state or stop for manual review.
8. Existing destinations are never overwritten.
9. Absolute paths and paths escaping the configured media root are rejected.
10. Cross-filesystem moves remain disabled until a copy/verify/delete transaction exists.
11. Source size/mtime fingerprints can be carried into plans so stale files are rejected at apply time.
12. Concurrent apply/rollback operations sharing the same state directory are locked out.
13. Audiobookshelf/Jellyfin databases are never edited directly.
14. Metadata embedding, deletion, and other destructive operations remain disabled until they have explicit rollback semantics.

A TrueNAS/ZFS snapshot before a large apply remains the second recovery layer above the application-level journal.

## Durable rollback design

The filesystem executor now uses a journal-first state machine:

```text
journal_created
  -> applying
      operation: pending -> applying -> applied
      operation: pending -> applying -> applied
      ...
  -> completed
```

Rollback processes completed operations in reverse order:

```text
applied -> rolling_back -> rolled_back
```

If the process/container dies after an atomic rename but before `applied` is persisted, the journal still contains `applying`. Rollback compares source and destination paths to determine whether the rename happened. Ambiguous states stop rather than guessing.

The journal embeds the original plan plus a SHA-256 integrity digest. A modified/corrupt plan payload is rejected during journal loading.

Currently enabled writes are deliberately limited to:

- same-filesystem move/rename;
- directory creation, reversed by empty-directory removal.

Current apply refuses:

- overwrite collisions;
- symlink sources;
- path traversal/root escapes;
- stale source fingerprints when the plan supplies them;
- cross-filesystem moves;
- generic metadata writes;
- any operation without a rollback definition.

## Phase 0 - Foundation and safety

- [x] Preserve legacy scripts rather than silently changing their behavior.
- [x] Add installable Python package and CLI entrypoint.
- [x] Add read-only recursive scanner for audio/video libraries.
- [x] Capture parent/sibling/child directory context for later LLM use.
- [x] Add schema/version markers for scan snapshots and plans.
- [x] Capture source size and modification time in scan snapshots.
- [x] Add explicit operation/plan models with reverse-order rollback generation.
- [x] Add durable atomic journal storage outside the media root.
- [x] Add guarded filesystem executor for reversible operations.
- [x] Add crash reconciliation for interrupted renames/moves.
- [x] Add journal plan-integrity checking.
- [x] Add collision, root-escape, symlink, stale-source, cross-filesystem, and concurrency protections.
- [x] Add `validate-plan`, `apply-plan`, `journal-status`, and `rollback` commands.
- [x] Add Dockerfile.
- [x] Add read-only-by-default TrueNAS Compose example with opt-in writer service.
- [x] Document TrueNAS deployment and rollback workflow.
- [x] Add unit coverage for scanning, parsing, apply, rollback, collision refusal, stale plans, and crash recovery.
- [ ] Add synthetic fixture generator with intentionally ugly audiobook/movie/show trees.
- [ ] Add structured logging.
- [ ] Add CI that runs the test suite and validates the Docker build.

### Exit condition

The core can safely observe a library and has a proven transaction boundary for future generated plans. No identity engine is required for this phase to be complete.

## Phase 1 - Audiobook analysis

- [ ] Read embedded tags from M4B/MP3/FLAC without mutating files.
- [ ] Detect audiobook item boundaries from folders and tracks.
- [x] Port useful written chapter-number parsing from the legacy script into tested functions.
- [x] Begin deterministic release-noise normalization while preserving transformation evidence.
- [ ] Expand normalization for separators, casing, bracketed tags, disc markers, release groups, and site suffixes.
- [ ] Extract title, author, narrator, series, sequence, ISBN, and ASIN when present.
- [ ] Infer likely title/author/series from directory hierarchy.
- [ ] Flag suspicious multi-book folders and split-book layouts.
- [ ] Produce an item-level read-only analysis report, not just file-level filename hints.
- [ ] Generate intentionally messy test fixtures for common audiobook layouts.

### Exit condition

A scan of the real audiobook dataset produces useful item-level proposed identities before any provider lookup or LLM call.

## Phase 2 - Audiobookshelf adapter and identification

- [ ] Configure Audiobookshelf base URL and API token through environment/file secrets.
- [ ] Import existing library item metadata and paths.
- [ ] Use Audiobookshelf APIs rather than direct database edits.
- [ ] Search Audiobookshelf-supported metadata providers.
- [ ] Normalize provider results into a common candidate model.
- [ ] Rank candidates using identifiers, title, author, series, narrator, duration, language, and existing folder context.
- [ ] Cache provider queries and add retry/rate-limit handling.
- [ ] Record evidence contributing to each score.
- [ ] Keep parsing confidence, identity confidence, edition confidence, and operation confidence separate.

### Exit condition

Most audiobooks have a ranked candidate list with understandable evidence and no automatic mutation.

## Phase 3 - Proposal generation and review

- [ ] Add SQLite state for snapshots, proposals, decisions, and audit events.
- [ ] Convert approved identity proposals into explicit filesystem/metadata plans.
- [ ] Populate source size/mtime fingerprints on generated filesystem operations.
- [ ] Build a small local web review queue.
- [ ] Show current vs proposed metadata/path and strongest evidence.
- [ ] Approve/edit/reject/ignore individual proposals.
- [ ] Batch-approve filtered high-confidence proposals manually.
- [ ] Detect case-only renames and generate a safe temporary-hop sequence where required.
- [ ] Verify post-apply state and report partial failures.
- [ ] Add a pre-apply reminder/check for a recent TrueNAS snapshot.

### Exit condition

A real audiobook cleanup can be generated, reviewed, applied through the existing journaled executor, verified, and rolled back.

## Phase 4 - Reversible server metadata updates

Filesystem rollback is implemented first because metadata rollback needs a different transaction model.

- [ ] Snapshot current Audiobookshelf metadata before every approved metadata update.
- [ ] Represent server metadata updates separately from filesystem operations.
- [ ] Persist before/after metadata in the durable journal/state database.
- [ ] Apply approved metadata through the Audiobookshelf API only.
- [ ] Implement metadata rollback using the captured previous values.
- [ ] Make mixed filesystem + server transactions report partial completion precisely.
- [ ] Trigger Audiobookshelf scans only when necessary.

### Exit condition

Metadata changes are as reversible and auditable as filesystem changes.

## Phase 5 - Local LLM context engine

- [ ] Add an Ollama-compatible adapter.
- [ ] Send bounded context: parent, siblings, filenames, embedded tags, file counts/durations, current server metadata, and candidate summaries.
- [ ] Require strict structured JSON output and validate it before use.
- [ ] Use the model for messy-name parsing, grouping hints, franchise/series context, and ambiguous candidate ranking.
- [ ] Never treat the model itself as identity evidence.
- [ ] Never expose filesystem or metadata mutation tools to the model.
- [ ] Log prompt inputs/outputs with secrets redacted.
- [ ] Make Ollama completely optional.

### Exit condition

Directories deterministic rules cannot understand become materially easier to identify, while disabling Ollama still leaves a functional cleanup tool.

## Phase 6 - Jellyfin movies and TV

- [ ] Add Jellyfin server adapter and library inventory.
- [ ] Detect movie vs show/season/episode structures.
- [ ] Normalize movies toward `Movie Name (year) [provider-id]/Movie Name (year) [provider-id].ext` when identity is verified.
- [ ] Normalize shows toward `Series Name (year) [provider-id]/Season 01/Series Name S01E01.ext`.
- [ ] Preserve subtitles, extras, alternate versions, and multi-part media.
- [ ] Use Jellyfin/provider metadata as evidence before renaming.
- [ ] Reuse the existing journaled filesystem executor rather than adding a Jellyfin-specific writer.
- [ ] Trigger targeted Jellyfin refreshes after approved changes.
- [ ] Optionally write verified local NFO metadata later, with captured previous content for rollback.

### Exit condition

The same review/apply engine safely fixes obvious movie and TV naming/structure problems without confusing versions, extras, or subtitles.

## Phase 7 - TrueNAS packaging and operation

The initial container shape is already present; this phase makes it convenient for long-term use.

- [x] Add Dockerfile.
- [x] Add TrueNAS/Docker Compose example.
- [x] Default normal media mount to read-only.
- [x] Separate write-capable service behind an explicit Compose profile.
- [x] Persist journal/state separately from media.
- [x] Run the image as a non-root user by default.
- [x] Drop container capabilities and enable `no-new-privileges` in the example deployment.
- [x] Add a basic container health check.
- [x] Document dataset permissions and deployment flow.
- [ ] Publish versioned container images to GHCR so TrueNAS can pull without a local build.
- [ ] Persist SQLite/config alongside journals in `/state`.
- [ ] Add web-service `/health` once the review UI exists.
- [ ] Add structured container logs.
- [ ] Optionally integrate TrueNAS API snapshot verification/creation before apply.

### Exit condition

The tool can be installed, upgraded, scanned, reviewed, applied, and rolled back on TrueNAS without a development checkout.

## Phase 8 - Quality-of-life automation

Only after the manual workflow is trusted:

- [ ] Scheduled read-only scans.
- [ ] Notifications when new messy/unidentified media appears.
- [ ] Reusable ignore/rule overrides for known weird libraries.
- [ ] Optional confidence-gated auto-approval for truly unambiguous metadata-only changes.
- [ ] Embedded audiobook metadata writes as a separate high-risk transaction type.
- [ ] Snapshot-aware rollback helper.

## Near-term implementation order

1. Add synthetic messy audiobook fixtures.
2. Add read-only embedded tag extraction.
3. Build folder/item-level audiobook grouping and identity parsing.
4. Add Audiobookshelf read/search adapter.
5. Add candidate/evidence scoring.
6. Add SQLite proposal state.
7. Generate real reviewed plans with source fingerprints.
8. Build the review UI.
9. Add reversible Audiobookshelf metadata transactions.
10. Add Ollama context assistance.
11. Add Jellyfin movie/TV adapter using the proven core.
12. Publish a versioned container image for easy TrueNAS deployment.
