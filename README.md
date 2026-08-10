# Audiobook Tools / Media Janitor

This repository started as small Python utilities for fixing audiobook chapter filenames. It is now being expanded into a personal, self-hosted media cleanup tool for messy Audiobookshelf and Jellyfin libraries on TrueNAS.

The new code is **read-only by default**. The intended workflow is:

```text
scan -> analyze -> identify -> plan -> review -> apply -> verify
```

A local Ollama-compatible model will be able to use folder, sibling, filename, tag, and server-metadata context to interpret unusually messy media. Model output will remain advisory: it will not receive direct filesystem or metadata write access.

See [ROADMAP.md](ROADMAP.md) for the implementation map.

## Current foundation

- recursive audiobook/video inventory
- directory, parent, sibling, and child context capture
- JSON scan snapshots
- read-only audiobook filename analysis
- written chapter-number parsing and special-section hints
- release-noise normalization with recorded transformations
- explicit file-operation plans
- automatically generated rollback operations for moves/renames
- no filesystem mutations in the new scanner/analyzer

## Development usage

Requires Python 3.11+.

```bash
python -m pip install -e .
media-janitor scan /path/to/media
media-janitor scan /path/to/media --json snapshot.json --pretty
media-janitor analyze-audiobooks /path/to/audiobooks
media-janitor analyze-audiobooks /path/to/audiobooks --json analysis.json --pretty
```

Run the tests with:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Legacy scripts

The original scripts remain at the repository root for now:

- `Audiobook tool(chapter reorder).py`
- `Audiobook tool(all numerical number removal).py`

They predate the safety model used by Media Janitor and rename files directly. Treat them as legacy utilities; the new implementation will port useful behavior into tested, dry-run-first modules rather than extending those scripts in place.
