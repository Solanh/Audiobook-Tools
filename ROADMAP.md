# Media Janitor Roadmap

This repository is evolving from two one-off audiobook renaming scripts into a personal, self-hosted media cleanup toolkit for a TrueNAS library. Audiobooks remain the first target, with Jellyfin movie/TV cleanup sharing the same scan, context, planning, review, and reversible filesystem-operation core.

## Primary goal

Point the tool at a messy media dataset, let it understand the surrounding directory context, propose a clean canonical structure and metadata, review uncertain cases, and apply only approved changes with a durable rollback journal.

The local LLM is a context interpreter, not an authority. It may parse names, infer grouping, and rank candidates, but it never directly mutates files or server metadata.

## Core workflow

```text
SCAN (read only)
  -> SNAPSHOT
  -> INSPECT (rules + embedded tags + folder context)
  -> MATCH CURRENT SERVER STATE (read only)
  -> IDENTIFY UNRESOLVED ITEMS (provider candidates + evidence + optional local LLM)
  -> PROPOSE
  -> REVIEW
  -> PLAN (explicit reversible operations + source fingerprints)
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
  metadata.py         read-only embedded audio metadata extraction
  audiobook.py        deterministic audiobook filename/chapter parsing
  items.py            local audiobook grouping and item-level evidence
  audiobookshelf.py   read-only Audiobookshelf inventory client
  matching.py         explainable local-to-server candidate scoring
  models.py           snapshots, versioned plans, reversible operations
  journal.py          durable atomic apply/rollback journal
  executor.py         guarded filesystem apply + rollback
  cli.py              read-only inspection/matching plus guarded write commands

  provider adapters/  planned
    audiobookshelf    metadata-provider search normalization and caching

  state/              planned
    sqlite             snapshots, proposals, decisions, audit events

  llm/                planned
    ollama             local structured context interpretation
    schemas            strict validated output

  web/                planned
    review queue       current vs proposed state, evidence, approve/edit/reject

  jellyfin/            planned
    inventory          server identity/metadata
    refresh            targeted post-apply refresh integration
```

The implementation can stay relatively flat until these pieces become large enough to justify deeper subpackages.

## Safety invariants

These are architectural requirements, not optional polish:

1. Scanning, inspection, matching, and provider lookup never mutate media.
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
15. Candidate output limits never hide runner-up evidence used to decide ambiguity.
16. Multiple local items cannot silently become strong assignments to the same server item.

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
- [x] Add an initial generated synthetic audiobook fixture set without real media content.
- [ ] Extend synthetic fixtures to Jellyfin movie/show trees when that adapter starts.
- [ ] Add structured logging.
- [x] Add CI that runs the test suite and validates the Docker build.

### Exit condition

The core can safely observe a library and has a proven transaction boundary for future generated plans. No identity engine is required for this phase to be complete.

## Phase 1 - Audiobook analysis

- [x] Read embedded tags from common M4B/MP3/FLAC-style audiobook formats without mutating files.
- [x] Detect basic audiobook item boundaries from folders/tracks, including common disc subfolders.
- [x] Port useful written chapter-number parsing from the legacy script into tested functions.
- [x] Begin deterministic release-noise normalization while preserving transformation evidence.
- [ ] Expand normalization for separators, casing, bracketed tags, disc markers, release groups, and site suffixes.
- [x] Extract title, author, narrator, series, sequence, ISBN, and ASIN when embedded metadata provides them.
- [ ] Infer likely title/author/series more deeply from multi-level directory hierarchy.
- [ ] Flag suspicious multi-book folders and split-book layouts before server matching.
- [x] Produce an item-level read-only analysis report, not just file-level filename hints.
- [x] Generate intentionally messy synthetic test layouts for common audiobook cases.

### Exit condition

A scan of the real audiobook dataset produces useful item-level proposed identities before any provider lookup or LLM call.

## Phase 2 - Audiobookshelf adapter and identification

- [x] Configure Audiobookshelf base URL and API credential through environment secrets.
- [x] Import existing library item metadata and paths read-only.
- [x] Use Audiobookshelf APIs rather than direct database edits.
- [x] Compare local inspection items to existing Audiobookshelf items before performing provider searches.
- [x] Rank current-server candidates using identifiers, title, author, series, narrator, duration, and path context.
- [x] Record positive and negative evidence contributing to each current-server score.
- [x] Prevent close runner-ups/output limits from creating false strong matches.
- [x] Detect duplicate strong assignments to one Audiobookshelf item and downgrade them for review.
- [ ] Search Audiobookshelf-supported metadata providers for unresolved items.
- [ ] Normalize provider results into a common candidate model.
- [ ] Rank provider candidates using identifiers, title, author, series, narrator, duration, language, and existing context.
- [ ] Cache provider queries and add retry/rate-limit handling.
- [ ] Keep parsing confidence, current-server match confidence, provider identity confidence, edition confidence, and operation confidence separate.

### Exit condition

Most audiobooks have a ranked candidate list with understandable evidence and no automatic mutation.

## Phase 3 - Proposal generation and review

- [ ] Add SQLite state for snapshots, server matches, provider candidates, proposals, decisions, and audit events.
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

1. Run `inspect-audiobooks` and `match-audiobookshelf` against a real read-only library and collect failure patterns.
2. Improve hierarchy inference and suspicious multi-book/split-layout detection from those patterns.
3. Add read-only Audiobookshelf metadata-provider search for unresolved items.
4. Normalize and score provider candidates with separate edition confidence.
5. Add SQLite snapshot/match/proposal/audit state under `/state`.
6. Generate real reviewed plans with source fingerprints from approved proposals.
7. Build the review UI.
8. Add reversible Audiobookshelf metadata transactions.
9. Add Ollama context assistance for ambiguous parsing/ranking only.
10. Add Jellyfin movie/TV adapter using the proven core.
11. Publish a versioned container image for easy TrueNAS deployment.
