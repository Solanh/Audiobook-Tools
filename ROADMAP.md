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
  -> IDENTIFY UNRESOLVED ITEMS (provider candidates + evidence)
  -> PERSIST REPORT
  -> STAGE PENDING PROPOSALS
  -> HUMAN REVIEW
  -> PLAN (explicit reversible operations + source fingerprints)
  -> SNAPSHOT/BACKUP CHECK
  -> APPLY (durable journal)
  -> VERIFY
  -> RESCAN AUDIOBOOKSHELF/JELLYFIN
       \
        -> ROLLBACK from journal if needed
```

The implementation currently reaches through **human review state**. Proposal approval is deliberately disconnected from plan generation and all media/server writes until the next safety layer is implemented.

## Architecture map

```text
media_janitor/
  scanner.py            filesystem inventory and directory context
  metadata.py           read-only embedded audio metadata extraction
  audiobook.py          deterministic filename/chapter parsing
  items.py              local audiobook grouping and item evidence
  audiobookshelf.py     read-only server inventory + provider-search client
  matching.py           explainable local-to-server candidate scoring
  provider_matching.py  separate provider identity/edition scoring
  state.py              SQLite reports, pending proposals, decisions, audit trail
  models.py             snapshots, versioned plans, reversible operations
  journal.py            durable atomic apply/rollback journal
  executor.py           guarded filesystem apply + rollback
  cli.py                observation, review-state, and guarded write commands

  llm/                  planned
    ollama               local structured context interpretation
    schemas              strict validated output

  web/                  planned
    review queue         current/proposed state, evidence, approve/edit/reject

  jellyfin/              planned
    inventory            server identity/metadata
    refresh              targeted post-apply refresh integration
```

## Safety invariants

These are architectural requirements, not optional polish:

1. Scanning, inspection, current-server matching, and provider lookup never mutate media.
2. A model/provider response never directly becomes a filesystem operation.
3. Provider identity confidence and audiobook-edition confidence remain separate.
4. Candidate output limits never hide runner-up evidence used to decide ambiguity.
5. Multiple local items cannot silently become strong assignments to the same server item.
6. Persisted observation reports and proposal candidates are content-hashed and verified on load.
7. Strong candidates may only be staged as `pending`; they are never automatically approved.
8. Proposal decisions are explicit, audited, and currently disconnected from all apply paths.
9. Every filesystem write comes from an explicit versioned plan.
10. Plans used for filesystem apply must be fully reversible.
11. The rollback journal is persisted outside the media root before the first write.
12. Journal updates are written atomically and fsynced.
13. Interrupted `applying`/`rolling_back` states must be reconcilable from filesystem state or stop for manual review.
14. Existing destinations are never overwritten.
15. Absolute paths and paths escaping the configured media root are rejected.
16. Cross-filesystem moves remain disabled until a copy/verify/delete transaction exists.
17. Source size/mtime fingerprints can be carried into plans so stale files are rejected at apply time.
18. Concurrent apply/rollback operations sharing the same state directory are locked out.
19. Audiobookshelf/Jellyfin databases are never edited directly.
20. Metadata embedding, deletion, and other destructive operations remain disabled until they have explicit rollback semantics.

A TrueNAS/ZFS snapshot before a large apply remains the second recovery layer above the application-level journal.

## Durable rollback design

The filesystem executor uses a journal-first state machine:

```text
journal_created
  -> applying
      operation: pending -> applying -> applied
      ...
  -> completed
```

Rollback processes completed operations in reverse order:

```text
applied -> rolling_back -> rolled_back
```

If the process/container dies after an atomic rename but before `applied` is persisted, rollback compares source and destination paths to determine whether the rename happened. Ambiguous states stop rather than guessing. The journal embeds the original plan plus a SHA-256 integrity digest.

Currently enabled writes are deliberately limited to same-filesystem move/rename and directory creation. Current apply refuses overwrite collisions, symlink sources, path escapes, stale source fingerprints, cross-filesystem moves, generic metadata writes, and any operation without rollback semantics.

## Phase 0 - Foundation and safety

- [x] Preserve legacy scripts rather than silently changing their behavior.
- [x] Add installable Python package and CLI entrypoint.
- [x] Add read-only recursive scanner for audio/video libraries.
- [x] Capture parent/sibling/child directory context.
- [x] Add schema/version markers and source size/mtime fingerprints.
- [x] Add reversible operation/plan models.
- [x] Add durable atomic journal storage outside the media root.
- [x] Add guarded filesystem executor and crash reconciliation.
- [x] Add journal integrity checking.
- [x] Add collision, root-escape, symlink, stale-source, cross-filesystem, and concurrency protections.
- [x] Add `validate-plan`, `apply-plan`, `journal-status`, and `rollback` commands.
- [x] Add Dockerfile and read-only-by-default TrueNAS Compose example.
- [x] Add generated synthetic audiobook fixtures without real media content.
- [x] Add CI for Python tests, Docker build, Compose validation, container apply, and rollback.
- [ ] Add structured logging.
- [ ] Extend synthetic fixtures to Jellyfin movie/show trees when that adapter starts.

## Phase 1 - Audiobook analysis

- [x] Read embedded tags from common M4B/MP3/FLAC-style audiobook formats without mutating files.
- [x] Detect basic audiobook item boundaries, including common disc subfolders.
- [x] Port written chapter-number parsing from the legacy script.
- [x] Begin deterministic release-noise normalization with transformation evidence.
- [x] Extract title, author, narrator, series, sequence, ISBN, and ASIN when embedded metadata provides them.
- [x] Produce item-level read-only analysis reports.
- [x] Generate intentionally messy synthetic test layouts.
- [ ] Expand normalization for more release-group/site/casing patterns.
- [ ] Infer likely title/author/series more deeply from multi-level directory hierarchy.
- [ ] Flag suspicious multi-book folders and split-book layouts before matching.

### Exit condition

A scan of the real audiobook dataset produces useful item-level proposed identities before any provider lookup or LLM call.

## Phase 2 - Audiobookshelf adapter and identification

- [x] Configure Audiobookshelf base URL and API credential through environment secrets.
- [x] Import existing library item metadata and paths read-only.
- [x] Use Audiobookshelf APIs rather than direct database edits.
- [x] Compare local items to existing Audiobookshelf items first.
- [x] Rank current-server candidates using identifiers, title, author, series, narrator, duration, and path context.
- [x] Record positive and negative evidence for current-server scores.
- [x] Protect against close runner-ups and duplicate assignments.
- [x] Discover Audiobookshelf-supported metadata providers at runtime.
- [x] Search a selected provider for unresolved items only.
- [x] Normalize provider results into a common candidate model.
- [x] Score provider book identity separately from audiobook-edition confidence.
- [x] Record provider score evidence and warnings for weak edition evidence.
- [x] Bound provider lookup volume with a per-run search cap.
- [ ] Cache provider queries.
- [ ] Add retry/backoff and explicit upstream rate-limit handling.
- [ ] Incorporate language/year/publisher evidence where it improves ranking safely.

### Exit condition

Most audiobooks have a ranked candidate list with understandable evidence and no automatic mutation.

## Phase 3 - Proposal generation and review

- [x] Add SQLite state under `/state` for immutable identification reports, staged proposals, decisions, and audit events.
- [x] Content-hash persisted reports and proposal candidates and verify them on load.
- [x] Stage strong provider identity candidates only behind an explicit flag and always as `pending`.
- [x] Add CLI review commands to list proposals and record `approved` / `rejected` / `ignored` decisions.
- [x] Keep proposal decisions disconnected from filesystem and server writes.
- [x] Reject review-state storage inside the media root.
- [ ] Convert explicitly approved proposals into inspectable draft filesystem/metadata plans.
- [ ] Populate source size/mtime fingerprints on generated filesystem operations.
- [ ] Build a small local web review queue.
- [ ] Show current vs proposed metadata/path and strongest evidence in the UI.
- [ ] Allow edit/approve/reject/ignore from the UI with the same audit trail.
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
- [ ] Implement metadata rollback using captured previous values.
- [ ] Make mixed filesystem + server transactions report partial completion precisely.
- [ ] Trigger Audiobookshelf scans only when necessary.

## Phase 5 - Local LLM context engine

- [ ] Add an Ollama-compatible adapter.
- [ ] Send bounded context: parent, siblings, filenames, embedded tags, file counts/durations, current server metadata, and candidate summaries.
- [ ] Require strict structured JSON output and validate it before use.
- [ ] Use the model for messy-name parsing, grouping hints, franchise/series context, and ambiguous candidate ranking.
- [ ] Never treat the model itself as identity evidence.
- [ ] Never expose mutation tools to the model.
- [ ] Log prompt inputs/outputs with secrets redacted.
- [ ] Make Ollama completely optional.

## Phase 6 - Jellyfin movies and TV

- [ ] Add Jellyfin server adapter and library inventory.
- [ ] Detect movie vs show/season/episode structures.
- [ ] Normalize verified movies and shows toward Jellyfin-friendly canonical structures.
- [ ] Preserve subtitles, extras, alternate versions, and multi-part media.
- [ ] Use Jellyfin/provider metadata as evidence before renaming.
- [ ] Reuse the journaled filesystem executor.
- [ ] Trigger targeted Jellyfin refreshes after approved changes.
- [ ] Optionally write verified NFO metadata later with captured previous content for rollback.

## Phase 7 - TrueNAS packaging and operation

- [x] Add Dockerfile and TrueNAS/Docker Compose example.
- [x] Default normal media mount to read-only.
- [x] Separate write-capable service behind an explicit Compose profile.
- [x] Persist journal/state separately from media.
- [x] Persist SQLite review state alongside journals in `/state`.
- [x] Run the image as a non-root user by default.
- [x] Drop container capabilities and enable `no-new-privileges`.
- [x] Add a basic container health check and deployment documentation.
- [ ] Publish versioned container images to GHCR so TrueNAS can pull without a local build.
- [ ] Add web-service `/health` once the review UI exists.
- [ ] Add structured container logs.
- [ ] Optionally integrate TrueNAS API snapshot verification/creation before apply.

## Phase 8 - Quality-of-life automation

Only after the manual workflow is trusted:

- [ ] Scheduled read-only scans.
- [ ] Notifications when new messy/unidentified media appears.
- [ ] Reusable ignore/rule overrides for known weird libraries.
- [ ] Optional confidence-gated auto-approval for truly unambiguous metadata-only changes.
- [ ] Embedded audiobook metadata writes as a separate high-risk transaction type.
- [ ] Snapshot-aware rollback helper.

## Near-term implementation order

1. Run `inspect-audiobooks`, `match-audiobookshelf`, and capped `identify-audiobooks` against the real library and collect grouping/matching failure patterns.
2. Improve hierarchy inference and suspicious multi-book/split-layout detection from those patterns.
3. Add provider-query caching plus retry/backoff handling.
4. Generate **draft plans only** from explicitly approved proposals, carrying source fingerprints and no automatic apply behavior.
5. Build the local review UI on top of the existing SQLite/audit model.
6. Add post-plan verification and TrueNAS snapshot preflight.
7. Add reversible Audiobookshelf metadata transactions.
8. Add optional Ollama context assistance for ambiguous parsing/ranking only.
9. Add Jellyfin movie/TV support using the proven core.
10. Publish versioned container images for pull-only TrueNAS installation.
