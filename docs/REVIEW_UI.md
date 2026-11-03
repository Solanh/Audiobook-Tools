# Local review queue

Media Janitor includes a small local web UI for reviewing staged SQLite proposals. The UI changes **review state only**. It cannot read or write the media filesystem unless you separately mount media into its container, which the provided TrueNAS review service intentionally does not do.

## Local-only use

On the same machine as the state database, localhost needs no access token:

```bash
media-janitor review-server \
  --state-dir /state \
  --bind 127.0.0.1 \
  --port 8090
```

Open:

```text
http://127.0.0.1:8090
```

The UI lists pending, approved, rejected, and ignored proposals. Proposal details show the local item path, provider metadata, identity and edition scores, current-server match status, identifiers, candidate digest, warnings, and the score evidence retained in SQLite.

## Network access

Any non-loopback bind requires an access token of at least 16 characters. Prefer a random token generated with Python:

```bash
export MEDIA_JANITOR_REVIEW_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"

media-janitor review-server \
  --state-dir /state \
  --bind 0.0.0.0 \
  --port 8090
```

The browser login form submits the configured token once. A successful login exchanges it for a random per-process session cookie. The configured access token itself is not placed in the browser cookie or URL.

The session disappears when the review server restarts.

For access outside a trusted LAN, put the review server behind a TLS reverse proxy or another trusted encrypted tunnel. The built-in server is intentionally small and serves HTTP; it is not intended to be an Internet-facing application server.

## Review actions

A pending proposal can be:

- approved;
- rejected;
- ignored.

A review note can be recorded with the decision. The same SQLite audit trail used by the CLI records the decision.

A final decision is immutable in the current state schema. Changed evidence should produce a new report/proposal instead of rewriting previous review history.

## Security boundary

The review server:

- defaults to loopback binding;
- requires an access token for non-loopback binding;
- exchanges the configured token for an ephemeral browser session;
- uses `HttpOnly` and `SameSite=Strict` on the browser session cookie;
- requires a per-process CSRF token on decision forms;
- caps accepted form-body size;
- emits a restrictive Content Security Policy;
- denies framing;
- disables browser caching;
- suppresses HTTP request logs that could expose authentication material;
- exposes only a minimal unauthenticated `/health` response.

Most importantly, the review module does not import or invoke the filesystem executor or Audiobookshelf write operations.

An `approved` proposal still means **approved in review state only**. The current UI cannot generate or apply a cleanup plan.

## TrueNAS review profile

The provided Compose file has an opt-in `review` profile. Set the token first:

```bash
export MEDIA_JANITOR_REVIEW_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

Then start only the review service:

```bash
docker compose -f compose.truenas.example.yaml \
  --profile review \
  up -d media-janitor-review
```

Open:

```text
http://TRUENAS_HOST:8090
```

Enter the token from `MEDIA_JANITOR_REVIEW_TOKEN` on the login page.

The example review container mounts only:

```text
/state:rw
```

It deliberately has **no `/media` mount**, even read-only. The separate writer profile remains the only provided container with a read/write media mount.

To use a different host port:

```bash
export MEDIA_JANITOR_REVIEW_PORT=18090
```

For a persistent Compose deployment, put the token in the deployment environment or an uncommitted `.env` file with restrictive permissions. Do not commit the token to the repository.
