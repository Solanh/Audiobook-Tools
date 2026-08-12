# Audiobook Tools / Media Janitor

This repository started as small Python utilities for fixing audiobook chapter filenames. It is now being expanded into a personal, self-hosted media cleanup tool for messy Audiobookshelf and Jellyfin libraries on TrueNAS.

The intended workflow is:

```text
scan -> inspect -> identify -> plan -> review -> apply -> verify
                                         \-> rollback if needed
```

A local Ollama-compatible model will be able to use folder, sibling, filename, tag, and server-metadata context to interpret unusually messy media. Model output remains advisory: it never receives direct filesystem or metadata write access.

See [ROADMAP.md](ROADMAP.md) for the implementation map and [docs/TRUENAS.md](docs/TRUENAS.md) for the container/TrueNAS setup.

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

Provider candidate search/scoring, persistent proposal state, and the review UI are still being built. The filesystem executor exists now so that future approved plans have a safe transaction boundary rather than adding rollback after the fact.

## Development usage

Requires Python 3.11+.

```bash
python -m pip install -e .
media-janitor scan /path/to/media
media-janitor scan /path/to/media --json snapshot.json --pretty
media-janitor analyze-audiobooks /path/to/audiobooks
media-janitor analyze-audiobooks /path/to/audiobooks --json analysis.json --pretty
media-janitor inspect-audiobooks /path/to/audiobooks
media-janitor inspect-audiobooks /path/to/audiobooks --json items.json --pretty
```

`inspect-audiobooks` is the preferred read-only command for real-library testing. It groups tracks into likely audiobook items, reads embedded tags when possible, records metadata-read failures without aborting the scan, and emits identity hints plus evidence/warnings. It does not generate or apply filesystem changes.

## Audiobookshelf read-only inventory

Create an Audiobookshelf API key for an account that can read the target library, then set it through the environment rather than putting the secret on the command line:

```bash
export AUDIOBOOKSHELF_URL='http://your-audiobookshelf-host:13378'
export AUDIOBOOKSHELF_API_KEY='your-api-key'

media-janitor audiobookshelf-inventory --json audiobookshelf.json --pretty
```

If the server has more than one book library, pass the library ID explicitly:

```bash
media-janitor audiobookshelf-inventory --library-id lib_xxxxxxxxx --json audiobookshelf.json --pretty
```

This command only performs GET requests. It normalizes the existing Audiobookshelf title, author, narrator, series, ASIN, ISBN, duration, and path data for later comparison with the filesystem inspection report. `AUDIOBOOKSHELF_TOKEN` is accepted as a legacy fallback, but API keys are preferred.

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

The current write executor targets Linux/TrueNAS so it can require `renameat2(RENAME_NOREPLACE)` rather than fall back to an overwrite-capable rename. Read-only scan/analyze/inspect commands remain portable.

The executor intentionally supports only operations with a defined rollback. Same-filesystem rename/move and directory creation are enabled; metadata writes, cross-filesystem copy/delete, and other destructive operations remain disabled until they have an equally strong recovery design.

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
