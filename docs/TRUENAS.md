# TrueNAS deployment

Media Janitor is currently a CLI-first tool. The container is useful as a persistent toolbox service on TrueNAS while the web review UI is still being built.

## Safety layout

Use two separate host-path mounts:

- `/media`: the actual media dataset.
- `/state`: a small persistent dataset for scan output, plans, journals, and future SQLite state.

The rollback journal **must not live inside `/media`**. `apply-plan` rejects that configuration. If a media directory is moved, the journal must remain available independently so the operation can be reconciled or reversed after a crash.

The example Compose file exposes the normal service with `/media:ro`. A second `media-janitor-writer` service is behind the `write` profile and mounts `/media:rw`. Do routine scanning and analysis through the read-only service; start the writer only for a reviewed apply or rollback.

A TrueNAS/ZFS snapshot immediately before a large apply is still recommended as a second recovery layer. The application journal protects logical renames/moves; a dataset snapshot protects against failures outside the application's control.

## Build the image

From the repository:

```bash
# Build once after pulling/updating the repo.
docker build -t media-janitor:local .
```

The image runs as UID/GID `10001:10001` by default. Either grant that identity access to the state dataset and read access to the media dataset, or change `user:` in the Compose YAML to a UID/GID that already has the intended TrueNAS dataset permissions.

## TrueNAS Compose example

Copy `compose.truenas.example.yaml`, replace the two `/mnt/tank/...` example host paths, and deploy it with TrueNAS **Apps -> Discover -> Install via YAML** or with Docker Compose from the host.

The normal container stays running so commands can be executed into it:

```bash
docker compose -f compose.truenas.example.yaml exec media-janitor \
  media-janitor scan /media --json /state/scan.json --pretty

docker compose -f compose.truenas.example.yaml exec media-janitor \
  media-janitor analyze-audiobooks /media --json /state/audiobooks.json --pretty
```

The media mount is read-only in that service, so these commands cannot rename media even if a future bug tries to write.

## Applying a reviewed plan

First validate it through the read-only container:

```bash
docker compose -f compose.truenas.example.yaml exec media-janitor \
  media-janitor validate-plan /state/plans/example.json
```

Then invoke the opt-in writer profile:

```bash
docker compose -f compose.truenas.example.yaml --profile write run --rm media-janitor-writer \
  media-janitor apply-plan /state/plans/example.json \
  --state-dir /state \
  --confirm-apply
```

Before the first filesystem operation, Media Janitor writes a journal under `/state/journals/`. Each operation transitions through a durable `applying` state before the filesystem call and `applied` after it. If the process dies between those writes, rollback inspects the source/destination paths to reconcile whether the atomic rename happened.

Current filesystem apply intentionally rejects:

- overwrite of an existing destination;
- absolute paths or paths that escape `/media`;
- symlink sources;
- cross-filesystem moves;
- operations without a defined rollback;
- concurrent apply/rollback processes using the same state directory.

These restrictions are deliberate. Copy/delete workflows and server metadata writes need their own reversible transaction design before they are enabled.

## Rollback

Inspect the journal first:

```bash
docker compose -f compose.truenas.example.yaml exec media-janitor \
  media-janitor journal-status /state/journals/PLAN_ID.json
```

Then use the writer profile to reverse only operations recorded as completed:

```bash
docker compose -f compose.truenas.example.yaml --profile write run --rm media-janitor-writer \
  media-janitor rollback /state/journals/PLAN_ID.json \
  --confirm-rollback
```

Rollback runs in reverse operation order. Directories created by a plan are removed only after moved files have been restored, and `rmdir` will fail rather than deleting a non-empty directory.

## Registry image

The repository currently provides the Dockerfile and Compose deployment shape but does not yet publish a versioned registry image. Publishing tagged images to GHCR is the next packaging step if installation should be entirely through the TrueNAS UI without building the image first.
