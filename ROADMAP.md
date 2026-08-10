# Media Janitor Roadmap

This repository is evolving from a pair of one-off audiobook renaming scripts into a personal, self-hosted media cleanup toolkit for a TrueNAS library. Audiobooks remain the first target, with Jellyfin movie/TV cleanup sharing the same scan, context, planning, review, and filesystem-operation core.

## Primary goal

Point the tool at a messy media dataset, let it understand the surrounding directory context, propose a clean canonical structure and metadata, review uncertain cases, and then apply only approved changes with a rollback manifest.

The local LLM is a context interpreter, not an authority. It may parse names and rank candidates, but it never directly mutates files or server metadata.

## Core workflow

```text
SCAN (read only)
  -> SNAPSHOT
  -> ANALYZE (rules + server metadata + local LLM context)
  -> IDENTIFY (provider candidates + evidence)
  -> PLAN (explicit operations)
  -> REVIEW
  -> SNAPSHOT/BACKUP CHECK
  -> APPLY
  -> VERIFY
  -> RESCAN AUDIOBOOKSHELF/JELLYFIN
```

## Architecture map

```text
media_janitor/
  core/
    scanner          filesystem inventory and directory context
    models           immutable snapshots, candidates, plans, operations
    rules            deterministic cleanup/parsing rules
    scorer           evidence and confidence calculation
    executor         approved filesystem operations only
    audit            manifests and operation history

  adapters/
    audiobookshelf   current metadata, provider search, approved updates, rescan
    jellyfin         current identity/metadata, refresh integration

  media/
    audiobooks       title/author/series/narrator/sequence logic
    movies           title/year/provider-id logic
    shows            series/season/episode logic

  llm/
    ollama           local structured-output context interpretation
    prompts          bounded directory-context prompts
    schemas          strict validated responses

  web/
    review queue     current vs proposed state, evidence, approve/edit/reject

  cli/
    scan/plan/apply/verify commands for administration and debugging
```

The initial implementation may keep modules flatter than this map until the code is large enough to justify subpackages.

## Data model

Every cleanup should be explainable and reversible. The durable concepts are:

- `ScanSnapshot`: immutable observation of the filesystem/server state.
- `DirectoryContext`: parent, siblings, child directories, and filenames for contextual inference.
- `ParsedIdentity`: what rules/LLM think the item name contains.
- `Candidate`: a possible real-world audiobook/movie/show identity from a provider.
- `Evidence`: title, author, narrator, duration, year, series, provider ID, etc.
- `Proposal`: desired canonical metadata and path plus confidence.
- `FileOperation`: one mkdir/move/rename/metadata write.
- `Plan`: ordered operations plus automatically generated rollback operations.
- `Decision`: approve/edit/reject/ignore.
- `AuditEvent`: what changed, when, and why.

## Confidence model

Do not collapse every decision into a single opaque score. Keep at least:

- parsing confidence: did we understand the messy input?
- identity confidence: did we identify the correct work?
- edition confidence: for audiobooks, is this the correct recording/narrator/edition?
- operation confidence: is this specific rename/move safe?

Auto-apply remains disabled until the manual workflow proves reliable.

## Phase 0 - Foundation (in progress)

- [x] Preserve legacy scripts rather than silently changing their behavior.
- [x] Add installable Python package and CLI entrypoint.
- [x] Add read-only recursive scanner for audio/video libraries.
- [x] Capture parent/sibling/child directory context for later LLM use.
- [x] Add explicit operation/plan models with reverse-order rollback generation.
- [x] Add basic unit tests for scanning/classification/rollback.
- [ ] Add JSON schema/version marker for scan snapshots and plans.
- [ ] Add fixture generator with intentionally ugly audiobook/movie/show names.
- [ ] Add structured logging.

### Exit condition

`media-janitor scan /path/to/library --json snapshot.json` can inventory a mounted TrueNAS dataset without modifying it and produces enough context for the next analysis layer.

## Phase 1 - Audiobook analysis

- [ ] Read embedded tags from M4B/MP3/FLAC without mutating files.
- [ ] Detect audiobook item boundaries from folders and tracks.
- [ ] Port useful chapter-number parsing from the legacy script into tested functions.
- [ ] Normalize common release noise, separators, casing, bracketed tags, codec/bitrate text, disc/chapter labels, and site suffixes.
- [ ] Extract title, author, narrator, series, sequence, ISBN, and ASIN when present.
- [ ] Preserve every transformation as evidence instead of discarding source text.
- [ ] Produce a read-only analysis report showing clean, suspicious, and unresolved items.

### Exit condition

A scan of the real audiobook dataset produces useful proposed identities before any network lookup or LLM call.

## Phase 2 - Audiobookshelf adapter and identification

- [ ] Configure Audiobookshelf base URL and API token through environment/file secrets.
- [ ] Import existing library item metadata and paths.
- [ ] Use Audiobookshelf provider/matching APIs rather than direct database edits.
- [ ] Normalize provider results into a common candidate model.
- [ ] Rank candidates using identifiers, title, author, series, narrator, duration, and language.
- [ ] Cache provider queries and add retry/rate-limit handling.
- [ ] Record the evidence contributing to each score.

Current Audiobookshelf APIs expose library item retrieval, matching, batch quick-match, library scan, and approved item media updates, so the first adapter should use those APIs rather than writing its database directly.

### Exit condition

Most audiobooks have a ranked candidate list with understandable evidence and no changes have been written automatically.

## Phase 3 - Review, apply, audit, and rollback

- [ ] Add SQLite state for snapshots, proposals, decisions, and audit events.
- [ ] Build a small local web review queue.
- [ ] Show current vs proposed metadata/path and the strongest evidence.
- [ ] Approve/edit/reject/ignore individual proposals.
- [ ] Batch-approve filtered high-confidence items manually.
- [ ] Generate a filesystem operation manifest before writes.
- [ ] Detect destination collisions, case-only renames, cross-filesystem moves, and missing sources.
- [ ] Create reverse rollback operations automatically.
- [ ] Apply approved Audiobookshelf metadata through the API.
- [ ] Verify post-write state and report partial failures.

### Exit condition

An audiobook cleanup can be reviewed and applied safely end to end, with a manifest that can undo renames/moves.

## Phase 4 - Local LLM context engine

- [ ] Add an Ollama-compatible adapter.
- [ ] Send bounded context: parent, siblings, filenames, embedded tags, file counts/durations, current server metadata, and candidate summaries.
- [ ] Require strict structured JSON output and validate it before use.
- [ ] Use the model for messy-name parsing, grouping hints, franchise/series context, and ambiguous candidate ranking.
- [ ] Never treat the model itself as identity evidence.
- [ ] Never expose filesystem or metadata mutation tools to the model.
- [ ] Log prompt inputs/outputs with secrets and sensitive paths redacted where appropriate.

### Exit condition

Directories that deterministic rules cannot understand become materially easier to identify, while disabling Ollama still leaves a functional cleanup tool.

## Phase 5 - Jellyfin movies and TV

- [ ] Add Jellyfin server adapter and library inventory.
- [ ] Detect movie vs show/season/episode structures.
- [ ] Normalize movies toward `Movie Name (year) [provider-id]/Movie Name (year) [provider-id].ext` when the identity is verified.
- [ ] Normalize shows toward `Series Name (year) [provider-id]/Season 01/Series Name S01E01.ext`.
- [ ] Preserve subtitles, extras, alternate versions, and multi-part media.
- [ ] Use Jellyfin/provider metadata as evidence before renaming.
- [ ] Trigger targeted Jellyfin refreshes after approved changes.
- [ ] Optionally write verified local NFO metadata later; do not do this by default because Jellyfin gives local NFO metadata priority.

### Exit condition

The same review/apply engine can safely clean obvious movie and TV naming/structure problems without confusing versions, extras, or subtitles.

## Phase 6 - TrueNAS deployment

- [ ] Add Dockerfile and Compose example.
- [ ] Default media mounts to read-only for scan/analyze services.
- [ ] Make write access an explicit deployment choice for apply operations.
- [ ] Persist SQLite/config/audit state separately from media.
- [ ] Add `/health` and structured container logs.
- [ ] Document TrueNAS Custom App/Compose setup and dataset permissions.
- [ ] Add a pre-apply reminder/check for a recent TrueNAS snapshot.

### Exit condition

The tool can live next to Audiobookshelf/Jellyfin on TrueNAS and be used without a development checkout.

## Phase 7 - Quality-of-life automation

Only after the manual workflow is trusted:

- [ ] Scheduled read-only scans.
- [ ] Notifications when new messy/unidentified media appears.
- [ ] Reusable ignore/rule overrides for known weird libraries.
- [ ] Optional confidence-gated auto-approval for truly unambiguous metadata-only changes.
- [ ] Embedded audiobook metadata writes as a separate high-risk operation.
- [ ] Snapshot-aware automatic rollback helper.

## Near-term implementation order

1. Finish the scan snapshot format and synthetic fixtures.
2. Add read-only embedded tag extraction.
3. Build deterministic audiobook filename/folder parsing.
4. Add `analyze` and `plan` CLI commands with no writes.
5. Add Audiobookshelf read/search integration.
6. Add SQLite proposal state and the review UI.
7. Add approved metadata/filesystem apply path.
8. Add Ollama context assistance.
9. Add Jellyfin movie/TV adapter using the proven core.
10. Package for TrueNAS.

## Safety invariants

These should stay true even as the project grows:

1. Scanning and analysis never mutate media.
2. A model/provider response never directly becomes a filesystem operation.
3. Every write comes from an explicit plan.
4. Every move/rename checks for destination collisions immediately before execution.
5. Original observed metadata/path is retained.
6. Filesystem plans include rollback operations where reversal is possible.
7. Audiobookshelf/Jellyfin databases are never edited directly.
8. Destructive or metadata-embedding operations remain opt-in and separate from normal cleanup.
