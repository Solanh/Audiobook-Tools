# Audiobook Tools / Media Janitor

This repository started as small Python utilities for fixing audiobook chapter filenames. It is now being expanded into a personal, self-hosted media cleanup tool for messy Audiobookshelf and Jellyfin libraries on TrueNAS.

The intended workflow is:

```text
scan -> analyze -> identify -> plan -> review -> apply -> verify
                                      \-> rollback if needed
```

A local Ollama-compatible model will be able to use folder, sibling, filename, tag, and server-metadata context to interpret unusually messy media. Model output remains advisory: it never receives direct filesystem or metadata write access.

See [ROADMAP.md](ROADMAP.md) for the implementation map and [docs/TRUENAS.md](docs/TRUENAS.md) for the container/TrueNAS setup.

## Current foundation

- recursive audiobook/video inventory
- directory, parent, sibling, and child context capture
- versioned JSON scan snapshots with source size/mtime information
- read-only audiobook filename analysis
- written chapter-number parsing and special-section hints
- release-noise normalization with recorded transformations
- versioned file-operation plans
- durable crash-safe apply journals written outside the media root
- reverse-order rollback for completed moves/renames/directories
- crash reconciliation if a rename completed before its journal state was persisted
- collision, path-escape, symlink, stale-source, and cross-filesystem protections
- irreversible metadata writes refused by the current executor
- Dockerfile plus a TrueNAS Compose example
- read-only media mount by default, with a separate opt-in writer service

The identification/planning/review layers are still being built. The filesystem executor exists now so that future generated plans have a safe transaction boundary rather than adding rollback after the fact.

## Development usage

Requires Python 3.11+.

```bash
python -m pip install -e .
media-janitor scan /path/to/media
media-janitor scan /path/to/media --json snapshot.json --pretty
media-janitor analyze-audiobooks /path/to/audiobooks
media-janitor analyze-audiobooks /path/to/audiobooks --json analysis.json --pretty
```

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

The current executor intentionally supports only operations with a defined rollback. Same-filesystem rename/move and directory creation are enabled; metadata writes, overwrite behavior, cross-filesystem copy/delete, and other destructive operations remain disabled until they have an equally strong recovery design.

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
