# Draft filesystem plans

Draft planning is the first bridge from human-approved review state to the existing reversible filesystem executor.

It is deliberately a **separate command from apply**.

## Preconditions

A proposal must already be `approved` in SQLite review state. Approval can come from the CLI or local review UI, but approval itself still performs no media changes.

Draft generation then re-verifies:

- the source report and proposal candidate hashes;
- the media root from the source identification report;
- every approved audiobook source path;
- source size and modification-time fingerprints;
- destination collisions;
- symlinks inside the item tree;
- whether additional unapproved audio files appeared in the approved item folder.

If any of those checks fail, no draft plan is written.

## Generate a draft

```bash
media-janitor-draft PROPOSAL_ID \
  --state-dir /state \
  --layout author-series-title \
  --pretty
```

By default the Plan JSON is written to:

```text
/state/plans/PROPOSAL_ID.json
```

A `draft-plan` report is also stored in the SQLite state database. That report ties the draft to:

- proposal id;
- source identification report id;
- candidate SHA-256 digest;
- chosen folder layout;
- source item path;
- target item path;
- companion-file list;
- complete generated Plan payload.

The plan file itself is a normal Media Janitor Plan JSON and can be passed to `media-janitor validate-plan` later.

## Supported layouts

### `author-series-title`

Default. With series metadata:

```text
Author/
  Series/
    01 - Title/
```

Without series metadata:

```text
Author/
  Title/
```

### `author-title`

```text
Author/
  Title/
```

### `series-title`

With series metadata:

```text
Series/
  01 - Title/
```

If series metadata is absent it falls back to `Author/Title`, then title-only if no usable author exists.

Provider-derived path components are sanitized before becoming filesystem names.

## What the first planner changes

The current planner creates only operations the existing executor can roll back:

- destination-directory creation;
- same-filesystem file moves.

It **preserves existing filenames**. It does not rename chapters/tracks and does not write embedded tags.

For example:

```text
Incoming/The Final Empire/Disc 1/01.mp3
```

may become:

```text
Brandon Sanderson/Mistborn/01 - The Final Empire/Disc 1/01.mp3
```

The nested relative structure below the original audiobook item is retained.

## Companion files

When an approved audiobook lives in its own item folder, normal non-audio companion files under that folder are carried with it, including things such as covers, OPF/NFO metadata, cue sheets, PDFs, and text files.

Each companion file receives a live size/mtime fingerprint in the generated plan.

The planner takes a stricter approach to audio: if it discovers an audio file in the item tree that was not part of the approved item report, it stops. That may mean the folder actually contains multiple books, an unexpected bonus audio layout, or stale grouping evidence that needs another inspection/review pass.

Root-level audiobook items do not absorb unrelated root-level companion files because ownership cannot be inferred safely there.

## Old source directories

The first draft planner does not remove the old source directory after moving files. Empty old folders may therefore remain after a successful apply.

This is intentional. Generic source-directory deletion is not currently represented as a fully reversible operation, so it is preferable to leave an empty directory than weaken the rollback model.

## Plan output safety

Draft generation refuses to:

- write the plan file inside the media root;
- overwrite an existing plan file;
- produce a plan from a pending/rejected/ignored proposal;
- produce a plan from stale source fingerprints;
- overwrite an existing destination;
- include an unapproved extra audio file.

It validates the generated Plan through the existing executor validation logic before writing the file.

## Applying remains separate

Draft generation ends with:

```text
apply_performed: false
```

Review the generated JSON and validate it again if desired:

```bash
media-janitor validate-plan /state/plans/PROPOSAL_ID.json
```

Only then, as a separate explicit action, can the existing writer be invoked:

```bash
media-janitor apply-plan /state/plans/PROPOSAL_ID.json \
  --state-dir /state \
  --confirm-apply
```

Apply performs its own collision and stale-source checks again, writes the durable rollback journal before the first mutation, and remains independent from review approval/draft generation.
