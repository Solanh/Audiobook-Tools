# Audiobook Tools / Media Janitor

This repository started as small Python utilities for fixing audiobook chapter filenames. It is now a safety-first, self-hosted media cleanup tool for messy Audiobookshelf libraries on TrueNAS, with Jellyfin support planned later.

The intended workflow is:

```text
scan -> inspect -> match current server -> identify unresolved -> stage -> review -> plan -> apply -> verify
                                                                                         \-> rollback if needed
```

A local Ollama-compatible model is planned as an optional context interpreter for unusually messy media. Model/provider output is advisory and never receives direct filesystem or metadata write access.

See [ROADMAP.md](ROADMAP.md), [docs/MATCHING.md](docs/MATCHING.md), [docs/PROVIDER_SEARCH.md](docs/PROVIDER_SEARCH.md), [docs/STATE.md](docs/STATE.md), [docs/REVIEW_UI.md](docs/REVIEW_UI.md), and [docs/TRUENAS.md](docs/TRUENAS.md).

## Current capabilities

- recursive read-only audiobook/video inventory and directory context
- source size/mtime fingerprints in versioned scan snapshots
- filename/chapter parsing and release-noise normalization
- read-only embedded audiobook metadata extraction through TinyTag
- item-level audiobook grouping, including common disc subfolders
- title/author/narrator/series/ASIN/ISBN/duration evidence and confidence
- read-only Audiobookshelf library inventory
- explainable local-to-current-server matching
- runtime Audiobookshelf metadata-provider discovery and read-only provider search
- separate provider book-identity and audiobook-edition confidence
- bounded provider searches only for unresolved items
- SQLite reports, pending proposals, immutable review decisions, and audit events under `/state`
- SHA-256 verification of persisted reports and staged candidate payloads
- CLI and local web review queues for approve/reject/ignore decisions
- token-gated non-loopback review UI with CSRF/session protections
- reversible, journaled same-filesystem move/rename and directory creation
- crash reconciliation, stale-plan detection, collision refusal, symlink/path-escape protections, and rollback
- Docker/TrueNAS deployment with read-only media by default, an isolated review service, and a separate opt-in writer

The major remaining boundary is **approved proposal -> draft plan**. An approved proposal currently means approved in review state only; neither the CLI nor the web review UI can modify media or Audiobookshelf.

## Install for development

Requires Python 3.11+.

```bash
python -m pip install -e .
```

Start with a real-library read-only inspection:

```bash
media-janitor inspect-audiobooks /path/to/audiobooks \
  --json items.json \
  --pretty
```

## Audiobookshelf inventory and matching

Configure credentials through the environment:

```bash
export AUDIOBOOKSHELF_URL='http://your-audiobookshelf-host:13378'
export AUDIOBOOKSHELF_API_KEY='your-api-key'
```

Read current server state:

```bash
media-janitor audiobookshelf-inventory --json audiobookshelf.json --pretty
```

Compare local items to existing Audiobookshelf items:

```bash
media-janitor match-audiobookshelf /path/to/audiobooks \
  --json matches.json \
  --pretty
```

Close runner-ups prevent a strong match, and multiple local folders cannot silently become strong assignments to the same Audiobookshelf item.

## Read-only provider identification

Search only items not already strongly matched to current Audiobookshelf state:

```bash
media-janitor identify-audiobooks /path/to/audiobooks \
  --provider audible \
  --max-provider-searches 10 \
  --json identify.json \
  --pretty
```

Provider results report `identity_score` separately from `edition_score`. Missing or weak audiobook-edition evidence is surfaced rather than being promoted into a confident edition claim.

## Persist and stage review proposals

Persist an identification report outside the media root:

```bash
media-janitor identify-audiobooks /path/to/audiobooks \
  --state-dir /state \
  --json /state/identify.json \
  --pretty
```

Strong provider identity candidates are staged only when explicitly requested, and always start `pending`:

```bash
media-janitor identify-audiobooks /path/to/audiobooks \
  --state-dir /state \
  --stage-strong-proposals
```

CLI review remains available:

```bash
media-janitor proposal-list --state-dir /state --status pending
media-janitor proposal-decide PROPOSAL_ID \
  --state-dir /state \
  --decision approved \
  --note 'Reviewed identity and edition evidence'
media-janitor audit-list --state-dir /state
```

## Local web review queue

On the same machine as `/state`, localhost needs no token:

```bash
media-janitor review-server --state-dir /state
```

Open `http://127.0.0.1:8090`.

For a LAN-accessible bind, a sufficiently long token is mandatory:

```bash
export MEDIA_JANITOR_REVIEW_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
media-janitor review-server \
  --state-dir /state \
  --bind 0.0.0.0 \
  --port 8090
```

The login token is exchanged for a random in-memory browser session cookie; the configured token itself is not stored in the browser cookie or URL. The UI shows current/proposed metadata, identity and edition confidence, identifiers, warnings, candidate digest, and scoring evidence.

The UI updates SQLite review state only. See [docs/REVIEW_UI.md](docs/REVIEW_UI.md) for the security model and TrueNAS setup.

## Guarded filesystem writes

A manually supplied plan can be checked without writes:

```bash
media-janitor validate-plan /path/to/plan.json
```

Applying a plan requires an explicit confirmation and persistent journal state outside the media root:

```bash
media-janitor apply-plan /path/to/plan.json \
  --state-dir /state \
  --confirm-apply

media-janitor journal-status /state/journals/PLAN_ID.json

media-janitor rollback /state/journals/PLAN_ID.json \
  --confirm-rollback
```

The write executor intentionally refuses unsupported/destructive operations until they have equivalent rollback semantics.

## TrueNAS

The repository includes `Dockerfile`, `compose.truenas.example.yaml`, and [docs/TRUENAS.md](docs/TRUENAS.md).

The example separates capabilities:

- `media-janitor`: `/media:ro`, `/state:rw`
- `media-janitor-review` under the opt-in `review` profile: `/state:rw` only, **no media mount**
- `media-janitor-writer` under the opt-in `write` profile: `/media:rw`, `/state:rw`

A TrueNAS/ZFS snapshot before a large apply remains recommended as a second recovery layer.

## Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

CI also builds the Docker image, validates Compose, exercises containerized apply/rollback, starts the real review service, checks its HTTP health/login behavior, and verifies the review container has no `/media` mount.

## Legacy scripts

The original direct-renaming scripts remain at the repository root for historical compatibility:

- `Audiobook tool(chapter reorder).py`
- `Audiobook tool(all numerical number removal).py`

They predate the current safety model. New functionality belongs in the tested Media Janitor package rather than those scripts.
