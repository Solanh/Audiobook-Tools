# TrueNAS deployment

Media Janitor separates observation/review privileges from filesystem write privileges.

The example Compose file uses three services:

```text
media-janitor          /media:ro  /state:rw
media-janitor-review              /state:rw   (review profile)
media-janitor-writer   /media:rw  /state:rw   (write profile)
```

The review container deliberately receives **no `/media` mount at all**.

## Prepare datasets

Example host paths:

```text
/mnt/tank/media
/mnt/tank/apps/media-janitor
```

The container runs as UID/GID `10001:10001` by default. Grant that identity the intended permissions through the TrueNAS dataset ACL model, or change `user:` in the Compose YAML. Avoid broad recursive permission changes on an existing library.

Keep `/state` on a persistent dataset separate from media. It stores SQLite review state, reports, plans, and rollback journals.

## Build the image

Until versioned GHCR images are published:

```bash
git clone https://github.com/Solanh/Audiobook-Tools.git
cd Audiobook-Tools
docker build -t media-janitor:local .
```

Validate the example:

```bash
MEDIA_JANITOR_REVIEW_TOKEN=test-token-0123456789abcdef \
  docker compose -f compose.truenas.example.yaml \
  --profile review --profile write config >/dev/null
```

## Start the read-only toolbox

After replacing the example host paths:

```bash
docker compose -f compose.truenas.example.yaml up -d media-janitor
```

Read-only inspection:

```bash
docker compose -f compose.truenas.example.yaml exec media-janitor \
  media-janitor inspect-audiobooks /media \
  --json /state/items.json \
  --pretty
```

The normal service mounts `/media:ro`, so routine inspection cannot rename media.

## Identify and stage proposals

Pass Audiobookshelf credentials through the environment; do not commit them to Compose:

```bash
export AUDIOBOOKSHELF_URL='http://audiobookshelf:13378'
export AUDIOBOOKSHELF_API_KEY='your-api-key'
```

Then run the read-only identity pipeline and explicitly stage strong candidates as pending proposals:

```bash
docker compose -f compose.truenas.example.yaml exec \
  -e AUDIOBOOKSHELF_URL \
  -e AUDIOBOOKSHELF_API_KEY \
  media-janitor \
  media-janitor identify-audiobooks /media \
  --state-dir /state \
  --stage-strong-proposals \
  --json /state/identify.json \
  --pretty
```

Provider lookup and proposal staging do not modify media or Audiobookshelf metadata.

## Start the isolated review UI

Generate a random token:

```bash
export MEDIA_JANITOR_REVIEW_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

Start the opt-in review service:

```bash
docker compose -f compose.truenas.example.yaml \
  --profile review \
  up -d media-janitor-review
```

Open:

```text
http://TRUENAS_HOST:8090
```

Enter the token on the login page. The configured token is exchanged for a random per-process browser session and is not stored in the browser cookie or URL.

The review service:

- exposes port 8090 by default;
- refuses non-loopback startup without a sufficiently long token;
- mounts `/state:rw`;
- has **no `/media` mount**;
- has an HTTP `/health` check;
- can only update SQLite review decisions.

To change the host port:

```bash
export MEDIA_JANITOR_REVIEW_PORT=18090
```

For persistent deployment, store the token in the TrueNAS app environment or an uncommitted `.env` file with restrictive permissions. `.env` is ignored by this repository. Do not commit the token.

The built-in review server is HTTP. Use it on a trusted LAN or place it behind a TLS reverse proxy / trusted encrypted tunnel if traffic must cross an untrusted network.

See [REVIEW_UI.md](REVIEW_UI.md) for details.

## Review/audit state from the CLI

```bash
docker compose -f compose.truenas.example.yaml exec media-janitor \
  media-janitor proposal-list --state-dir /state --status pending

docker compose -f compose.truenas.example.yaml exec media-janitor \
  media-janitor audit-list --state-dir /state
```

An `approved` proposal is still review state only. No current command turns an approved proposal into a filesystem plan automatically.

## Applying a manually reviewed plan

First validate it through the read-only container:

```bash
docker compose -f compose.truenas.example.yaml exec media-janitor \
  media-janitor validate-plan /state/plans/example.json
```

Create/verify a TrueNAS/ZFS snapshot before any significant write.

Then invoke the separate opt-in writer profile:

```bash
docker compose -f compose.truenas.example.yaml --profile write run --rm media-janitor-writer \
  apply-plan /state/plans/example.json \
  --state-dir /state \
  --confirm-apply
```

Before the first filesystem operation, Media Janitor writes a durable journal under `/state/journals/`.

Current apply intentionally rejects overwrite collisions, path escapes, symlink sources/path components, stale source fingerprints, cross-filesystem moves, unsupported irreversible operations, and concurrent apply/rollback processes sharing the state directory.

## Rollback

Inspect the journal:

```bash
docker compose -f compose.truenas.example.yaml exec media-janitor \
  media-janitor journal-status /state/journals/PLAN_ID.json
```

Then use the writer profile:

```bash
docker compose -f compose.truenas.example.yaml --profile write run --rm media-janitor-writer \
  rollback /state/journals/PLAN_ID.json \
  --confirm-rollback
```

Rollback runs completed operations in reverse order and refuses ambiguous states rather than guessing.

## Operational boundaries

- Keep `/state` persistent and separate from media.
- Keep the normal service read-only on media.
- Keep the review service isolated from media entirely.
- Enable the writer profile only for a reviewed apply or rollback.
- Keep Audiobookshelf credentials and review tokens out of Git.
- Keep a ZFS snapshot before large write batches.
- Do not edit Audiobookshelf databases directly.

## Registry image

The repository currently provides the Dockerfile and Compose deployment shape but does not yet publish a versioned registry image. Tagged GHCR images remain a packaging milestone.
