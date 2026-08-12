from __future__ import annotations

import hmac
import html
import ipaddress
import json
import secrets
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

from .state import FINAL_PROPOSAL_STATUSES, PROPOSAL_STATUSES, ProposalRecord, StateError, StateStore

_COOKIE_NAME = "media_janitor_review"
_MAX_FORM_BYTES = 16 * 1024


class ReviewServerError(RuntimeError):
    pass


def _is_loopback_bind(bind: str) -> bool:
    value = bind.strip().lower()
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def validate_review_exposure(bind: str, access_token: str | None) -> None:
    if _is_loopback_bind(bind):
        return
    if not access_token:
        raise ValueError(
            "A review access token is required when binding outside localhost. "
            "Set MEDIA_JANITOR_REVIEW_TOKEN or pass --access-token."
        )
    if len(access_token) < 16:
        raise ValueError("Review access token must be at least 16 characters")


def _escape(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _score(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.3f}"
    return "unknown"


def _candidate_view(proposal: ProposalRecord) -> dict[str, Any]:
    candidate = proposal.candidate
    selected = candidate.get("selected_candidate") if isinstance(candidate.get("selected_candidate"), dict) else {}
    provider_result = selected.get("provider_result") if isinstance(selected.get("provider_result"), dict) else {}
    provider_match = candidate.get("provider_match") if isinstance(candidate.get("provider_match"), dict) else {}
    current_match = candidate.get("current_server_match") if isinstance(candidate.get("current_server_match"), dict) else {}

    authors = provider_result.get("authors") if isinstance(provider_result.get("authors"), list) else []
    narrators = provider_result.get("narrators") if isinstance(provider_result.get("narrators"), list) else []
    series_values = provider_result.get("series") if isinstance(provider_result.get("series"), list) else []
    series: list[str] = []
    for item in series_values:
        if isinstance(item, dict):
            name = item.get("name")
            sequence = item.get("sequence")
            if name:
                series.append(f"{name} #{sequence}" if sequence else str(name))

    return {
        "title": provider_result.get("title") or proposal.local_item_path,
        "authors": ", ".join(str(value) for value in authors if value),
        "narrators": ", ".join(str(value) for value in narrators if value),
        "series": ", ".join(series),
        "asin": provider_result.get("asin"),
        "isbn": provider_result.get("isbn"),
        "provider": provider_result.get("provider") or provider_match.get("provider"),
        "identity_score": selected.get("identity_score"),
        "edition_score": selected.get("edition_score"),
        "provider_status": provider_match.get("status"),
        "current_server_status": current_match.get("status"),
        "provider_warnings": provider_match.get("warnings") if isinstance(provider_match.get("warnings"), list) else [],
        "evidence": selected.get("evidence") if isinstance(selected.get("evidence"), list) else [],
    }


def _page(title: str, body: str) -> bytes:
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_escape(title)} · Media Janitor</title>
<style>
:root {{ color-scheme: light dark; font-family: ui-sans-serif, system-ui, sans-serif; }}
body {{ max-width: 1100px; margin: 0 auto; padding: 24px; line-height: 1.45; }}
a {{ color: inherit; }}
header {{ display:flex; gap:16px; align-items:baseline; justify-content:space-between; border-bottom:1px solid #8886; margin-bottom:24px; }}
nav a {{ margin-right:12px; }}
.card {{ border:1px solid #8886; border-radius:10px; padding:16px; margin:14px 0; }}
.meta {{ opacity:.75; font-size:.92rem; }}
.score {{ display:inline-block; padding:2px 8px; border:1px solid #8888; border-radius:999px; margin-right:6px; }}
.warning {{ border-left:4px solid currentColor; padding-left:12px; margin:10px 0; }}
.actions {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:18px; }}
button {{ padding:8px 14px; cursor:pointer; }}
textarea {{ width:100%; min-height:72px; box-sizing:border-box; }}
pre {{ overflow:auto; white-space:pre-wrap; word-break:break-word; border:1px solid #8885; padding:12px; border-radius:8px; }}
table {{ border-collapse:collapse; width:100%; }}
th, td {{ text-align:left; border-bottom:1px solid #8884; padding:8px; vertical-align:top; }}
.badge {{ font-size:.85rem; padding:2px 7px; border:1px solid #8888; border-radius:999px; }}
</style>
</head>
<body>
<header><div><h1>Media Janitor</h1><p class="meta">Review state only — no media or Audiobookshelf writes</p></div><nav><a href="/">Queue</a><a href="/?status=approved">Approved</a><a href="/?status=rejected">Rejected</a><a href="/?status=ignored">Ignored</a></nav></header>
{body}
</body>
</html>"""
    return document.encode("utf-8")


def _render_queue(store: StateStore, status: str) -> bytes:
    proposals = store.list_proposals(status=status, limit=500)
    cards: list[str] = []
    for proposal in proposals:
        view = _candidate_view(proposal)
        cards.append(
            f"""<article class="card">
<div class="meta"><span class="badge">{_escape(proposal.status)}</span> {_escape(proposal.local_item_path)}</div>
<h2><a href="/proposal/{quote(proposal.proposal_id, safe='')}">{_escape(view['title'])}</a></h2>
<p>{_escape(view['authors'] or 'Unknown author')}</p>
<p><span class="score">identity {_escape(_score(view['identity_score']))}</span><span class="score">edition {_escape(_score(view['edition_score']))}</span></p>
<p class="meta">provider: {_escape(view['provider'] or 'unknown')} · staged {_escape(proposal.created_at)}</p>
</article>"""
        )
    if not cards:
        cards.append(f'<p class="meta">No {_escape(status)} proposals.</p>')
    body = f"<h2>{_escape(status.title())} proposals <span class=\"badge\">{len(proposals)}</span></h2>" + "".join(cards)
    return _page("Review queue", body)


def _render_proposal(proposal: ProposalRecord, csrf_token: str, *, saved: bool = False) -> bytes:
    view = _candidate_view(proposal)
    warnings = "".join(f'<div class="warning">{_escape(value)}</div>' for value in view["provider_warnings"])
    evidence_json = json.dumps(view["evidence"], indent=2, ensure_ascii=False)
    saved_banner = '<p class="warning">Decision recorded.</p>' if saved else ""

    details = f"""
{saved_banner}
<p><a href="/">← Back to queue</a></p>
<div class="card">
<div class="meta">{_escape(proposal.local_item_path)} · <span class="badge">{_escape(proposal.status)}</span></div>
<h2>{_escape(view['title'])}</h2>
<table>
<tr><th>Authors</th><td>{_escape(view['authors'] or 'Unknown')}</td></tr>
<tr><th>Narrators</th><td>{_escape(view['narrators'] or 'Unknown')}</td></tr>
<tr><th>Series</th><td>{_escape(view['series'] or 'None')}</td></tr>
<tr><th>ASIN</th><td>{_escape(view['asin'] or 'Unknown')}</td></tr>
<tr><th>ISBN</th><td>{_escape(view['isbn'] or 'Unknown')}</td></tr>
<tr><th>Provider</th><td>{_escape(view['provider'] or 'Unknown')}</td></tr>
<tr><th>Provider status</th><td>{_escape(view['provider_status'] or 'Unknown')}</td></tr>
<tr><th>Current server match</th><td>{_escape(view['current_server_status'] or 'Unknown')}</td></tr>
<tr><th>Identity score</th><td>{_escape(_score(view['identity_score']))}</td></tr>
<tr><th>Edition score</th><td>{_escape(_score(view['edition_score']))}</td></tr>
<tr><th>Candidate digest</th><td><code>{_escape(proposal.candidate_sha256)}</code></td></tr>
</table>
{warnings}
<h3>Candidate evidence</h3>
<pre>{_escape(evidence_json)}</pre>
</div>
"""

    if proposal.status == "pending":
        action = f"/proposal/{quote(proposal.proposal_id, safe='')}/decision"
        details += f"""
<div class="card">
<h3>Record review decision</h3>
<p class="meta">This changes SQLite review state only. It does not generate or apply a filesystem plan.</p>
<form method="post" action="{action}">
<input type="hidden" name="csrf" value="{_escape(csrf_token)}">
<label for="note">Review note</label>
<textarea id="note" name="note" maxlength="4000" placeholder="What did you verify?"></textarea>
<div class="actions">
<button type="submit" name="decision" value="approved">Approve</button>
<button type="submit" name="decision" value="rejected">Reject</button>
<button type="submit" name="decision" value="ignored">Ignore</button>
</div>
</form>
</div>"""
    elif proposal.decision_note:
        details += f'<div class="card"><h3>Decision note</h3><p>{_escape(proposal.decision_note)}</p></div>'

    return _page(str(view["title"]), details)


def create_review_server(
    store: StateStore,
    *,
    bind: str = "127.0.0.1",
    port: int = 8090,
    access_token: str | None = None,
) -> ThreadingHTTPServer:
    validate_review_exposure(bind, access_token)
    if not (0 <= port <= 65535):
        raise ValueError("Review server port must be between 0 and 65535")

    store.initialize()
    csrf_token = secrets.token_urlsafe(32)
    token = access_token or None

    class ReviewHandler(BaseHTTPRequestHandler):
        server_version = "MediaJanitorReview/0.1"

        def log_message(self, format: str, *args: object) -> None:
            # Avoid logging query strings, which may contain the one-time access token.
            return

        def _security_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            )
            self.send_header("Cache-Control", "no-store")

        def _send_html(self, payload: bytes, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_response(status)
            self._security_headers()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_text(self, text: str, status: HTTPStatus) -> None:
            payload = text.encode("utf-8")
            self.send_response(status)
            self._security_headers()
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_json(self, value: object, status: HTTPStatus = HTTPStatus.OK) -> None:
            payload = (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")
            self.send_response(status)
            self._security_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _cookie_token(self) -> str | None:
            raw = self.headers.get("Cookie")
            if not raw:
                return None
            cookie = SimpleCookie()
            try:
                cookie.load(raw)
            except Exception:
                return None
            morsel = cookie.get(_COOKIE_NAME)
            return morsel.value if morsel else None

        def _authorized(self) -> bool:
            if token is None:
                return True
            cookie_value = self._cookie_token()
            if cookie_value and hmac.compare_digest(cookie_value, token):
                return True
            authorization = self.headers.get("Authorization", "")
            if authorization.startswith("Bearer "):
                supplied = authorization[7:]
                if hmac.compare_digest(supplied, token):
                    return True
            return False

        def _consume_query_token(self) -> bool:
            if token is None:
                return False
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            supplied = query.get("token", [""])[0]
            if not supplied or not hmac.compare_digest(supplied, token):
                return False
            cleaned_query = {key: value for key, value in query.items() if key != "token"}
            location = parsed.path
            if cleaned_query:
                location += "?" + urlencode(cleaned_query, doseq=True)
            self.send_response(HTTPStatus.SEE_OTHER)
            self._security_headers()
            self.send_header("Location", location or "/")
            self.send_header(
                "Set-Cookie",
                f"{_COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict",
            )
            self.end_headers()
            return True

        def _require_auth(self) -> bool:
            if self._authorized():
                return True
            self._send_text(
                "Review access token required. Open the review URL with ?token=<token> once to establish a browser cookie.",
                HTTPStatus.UNAUTHORIZED,
            )
            return False

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            if parsed.path == "/health":
                self._send_json({"status": "ok", "database": str(store.path)})
                return
            if self._consume_query_token():
                return
            if not self._require_auth():
                return

            if parsed.path == "/":
                query = parse_qs(parsed.query)
                status = query.get("status", ["pending"])[0]
                if status not in PROPOSAL_STATUSES:
                    self._send_text("Unknown proposal status", HTTPStatus.BAD_REQUEST)
                    return
                try:
                    self._send_html(_render_queue(store, status))
                except StateError as error:
                    self._send_text(str(error), HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            if parsed.path.startswith("/proposal/"):
                proposal_id = unquote(parsed.path[len("/proposal/") :]).strip("/")
                if not proposal_id or "/" in proposal_id:
                    self._send_text("Not found", HTTPStatus.NOT_FOUND)
                    return
                try:
                    proposal = store.get_proposal(proposal_id)
                    saved = parse_qs(parsed.query).get("saved", [""])[0] == "1"
                    self._send_html(_render_proposal(proposal, csrf_token, saved=saved))
                except StateError:
                    self._send_text("Proposal not found", HTTPStatus.NOT_FOUND)
                return

            self._send_text("Not found", HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            if not self._require_auth():
                return
            parsed = urlsplit(self.path)
            prefix = "/proposal/"
            suffix = "/decision"
            if not (parsed.path.startswith(prefix) and parsed.path.endswith(suffix)):
                self._send_text("Not found", HTTPStatus.NOT_FOUND)
                return

            proposal_id = unquote(parsed.path[len(prefix) : -len(suffix)]).strip("/")
            if not proposal_id or "/" in proposal_id:
                self._send_text("Not found", HTTPStatus.NOT_FOUND)
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send_text("Invalid content length", HTTPStatus.BAD_REQUEST)
                return
            if length <= 0 or length > _MAX_FORM_BYTES:
                self._send_text("Invalid form size", HTTPStatus.BAD_REQUEST)
                return
            content_type = self.headers.get("Content-Type", "")
            if not content_type.startswith("application/x-www-form-urlencoded"):
                self._send_text("Unsupported content type", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
                return

            raw = self.rfile.read(length).decode("utf-8", errors="strict")
            form = parse_qs(raw, keep_blank_values=True)
            supplied_csrf = form.get("csrf", [""])[0]
            if not supplied_csrf or not hmac.compare_digest(supplied_csrf, csrf_token):
                self._send_text("Invalid CSRF token", HTTPStatus.FORBIDDEN)
                return
            decision = form.get("decision", [""])[0]
            if decision not in FINAL_PROPOSAL_STATUSES:
                self._send_text("Invalid proposal decision", HTTPStatus.BAD_REQUEST)
                return
            note = form.get("note", [""])[0].strip()
            if len(note) > 4000:
                self._send_text("Review note is too long", HTTPStatus.BAD_REQUEST)
                return

            try:
                store.decide_proposal(proposal_id, decision, note=note or None)
            except StateError as error:
                self._send_text(str(error), HTTPStatus.CONFLICT)
                return

            self.send_response(HTTPStatus.SEE_OTHER)
            self._security_headers()
            self.send_header("Location", f"/proposal/{quote(proposal_id, safe='')}?saved=1")
            self.end_headers()

    return ThreadingHTTPServer((bind, port), ReviewHandler)


def serve_review_queue(
    state_dir: str | Path,
    *,
    bind: str = "127.0.0.1",
    port: int = 8090,
    access_token: str | None = None,
) -> None:
    store = StateStore.from_state_dir(state_dir)
    server = create_review_server(store, bind=bind, port=port, access_token=access_token)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
