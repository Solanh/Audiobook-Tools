# Audiobook Tools / Media Janitor

This repository started as small Python utilities for fixing audiobook chapter filenames. It is now being expanded into a personal, self-hosted media cleanup tool for messy Audiobookshelf and Jellyfin libraries on TrueNAS.

The intended workflow is:

```text
scan -> inspect -> match current server -> identify unresolved -> propose -> review -> apply -> verify
                                                                               \-> rollback if needed
```

A local Ollama-compatible model will be able to use folder, sibling, filename, tag, and server-metadata context to interpret unusually messy media. Model output remains advisory: it never receives direct filesystem or metadata write access.

See [ROADMAP.md](ROADMAP.md) for the implementation map, [docs/MATCHING.md](docs/MATCHING.md) for current-server matching, [docs/PROVIDER_SEARCH.md](docs/PROVIDER_SEARCH.md) for provider identification, and [docs/TRUENAS.md](docs/TRUENAS.md) for container/TrueNAS setup.

## Current foundation

- recursive audiobook/video inventory
- directory, parent, sibling, and child context capture
- versioned JSON scan snapshots with source size/mtime information
- read-only audiobook filename analysis
- read-only embedded metadata extraction for common audiobook formats through TinyTag
- item-level audiobook grouping, including common `Disc 1` / `CD 2` layouts
- aggregated title/author/narrator/series/identifier hints with evidence and warnings
- conservative item confidence scoring; conflicting metadata is surfaced instead of silently chosen
- read-only Audiobookshelf library/item inventory through API-key Bearer authentication
- explainable local-to-Audiobookshelf candidate scoring using identifiers, title, author, narrator, series, duration, and path evidence
- ambiguity protection for close runner-ups and duplicate local folders targeting the same Audiobookshelf item
- read-only Audiobookshelf metadata-provider discovery and book search
- separate provider book-identity and audiobook-edition confidence
- capped provider lookups only for items not already strongly matched to current Audiobookshelf state
- synthetic messy-layout fixtures without storing real audiobook content
- written chapter-number parsing and special-section hints
- release-noise normalization with recorded transformations
- versioned file-operation plans
- durable crash-safe apply journals written outside the media root
- reverse-order rollback for completed moves/renames/directories
- crash reconciliation if a rename completed before its journal state was persisted
- atomic Linux no-replace renames so a late destination race cannot overwrite media
- collision, path-escape, symlink, stale-source, and cross-filesystem protections
- irreversible metadata writes refused by the current executor
- Dockerfile plus a TrueNAS Compose example
- read-only media mount by default, with a separate opt-in writer service

Persistent proposal state and the review UI are still being built. Provider results remain evidence only; they do not authorize writes.

## Development usage

Requires Python 3.11+.

```bash
python -m pip install -e .
media-janitor scan /path/to/media
media-janitor inspect-audiobooks /path/to/audiobooks --json items.json --pretty
```

`inspect-audiobooks` is the preferred first command for real-library testing. It groups tracks into likely audiobook items, reads embedded tags where possible, records metadata failures without aborting the scan, and emits item-level evidence/warnings without making changes.

## Audiobookshelf read-only inventory and current-server matching

Configure the server through environment variables rather than putting credentials on the command line:

```bash
export AUDIOBOOKSHELF_URL='http://your-audiobookshelf-host:13378'
export AUDIOBOOKSHELF_API_KEY='your-api-key'

media-janitor audiobookshelf-inventory --json audiobookshelf.json --pretty
media-janitor match-audiobookshelf /path/to/audiobooks --json matches.json --pretty
```

If the server has more than one book library, pass `--library-id`.

`match-audiobookshelf` scans the local tree, reads current Audiobookshelf items, and ranks current-server candidates with explicit score contributions. Results are labeled `strong_candidate`, `ambiguous`, or `no_candidate`. Close runner-ups prevent a strong label, and multiple local folders cannot silently become strong assignments to the same Audiobookshelf item.

## Read-only provider identification

For items not already strongly matched to current Audiobookshelf state:

```bash
media-janitor identify-audiobooks /path/to/audiobooks \
  --provider audible \
  --max-provider-searches 10 \
  --json identify.json \
  --pretty
```

The command discovers the providers exposed by the Audiobookshelf server, validates the selected slug, and searches only unresolved local items. `audible` is the default because audiobook-specific results can provide ASIN, narrator, duration, series, language, and abridged state. Other server-supported providers can be selected explicitly.

Provider results report `identity_score` separately from `edition_score`. A result can therefore be a strong book identity without claiming that it is the same audiobook edition. Missing or weak edition evidence is surfaced as a warning.

Provider search is capped at 10 unresolved items per run by default. Increase `--max-provider-searches` deliberately after inspecting initial results.

All inventory, matching, and identification commands are observation-only. They do not rename files, update Audiobookshelf metadata, trigger library scans, approve candidates, or create executable cleanup plans.

## Guarded filesystem writes

A plan can be checked without writes:

```bash
media-janitor validate-plan /path/to/plan.json
```

Filesystem writes require an explicit confirmation and a persistent state directory outside the media root:

```bash
media-janitor apply-plan /path/to/plan.json \
  --state-dir /state \
  --confirm-apply

media-janitor journal-status /state/journals/PLAN_ID.json

media-janitor rollback /state/journals/PLAN_ID.json \
  --confirm-rollback
```

The current write executor targets Linux/TrueNAS so it can require `renameat2(RENAME_NOREPLACE)` rather than fall back to an overwrite-capable rename. It intentionally supports only operations with a defined rollback. Same-filesystem rename/move and directory creation are enabled; metadata writes, cross-filesystem copy/delete, and other destructive operations remain disabled.

Run the tests with:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## TrueNAS

The repository includes:

- `Dockerfile`
- `compose.truenas.example.yaml`
- [TrueNAS deployment instructions](docs/TRUENAS.md)

The normal service mounts `/media` read-only. A separate writer service under the Compose `write` profile mounts it read/write only for an explicitly reviewed apply or rollback. `/state` is persistent and separate so rollback journals cannot be moved along with the media they protect.

A TrueNAS/ZFS snapshot before a large apply is still recommended as a second recovery layer.

## Legacy scripts

The original scripts remain at the repository root for now:

- `Audiobook tool(chapter reorder).py`
- `Audiobook tool(all numerical number removal).py`

They predate the safety model used by Media Janitor and rename files directly. Treat them as legacy utilities; the new implementation ports useful behavior into tested, dry-run-first modules rather than extending those scripts in place.
