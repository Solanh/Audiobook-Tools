from __future__ import annotations

import http.cookiejar
import re
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

from media_janitor.review import create_review_server, validate_review_exposure
from media_janitor.state import StateStore


class ReviewServerTests(unittest.TestCase):
    def _store_with_proposal(self, root: Path):
        store = StateStore.from_state_dir(root / "state")
        report = store.save_report("identify-audiobooks", {"records": []})
        candidate = {
            "current_server_match": {"status": "ambiguous"},
            "provider_match": {
                "provider": "audible",
                "status": "strong_identity_candidate",
                "warnings": [],
            },
            "selected_candidate": {
                "identity_score": 0.96,
                "edition_score": 0.91,
                "provider_result": {
                    "provider": "audible",
                    "title": "Warbreaker",
                    "authors": ["Brandon Sanderson"],
                    "narrators": ["Alyssa Bresnahan"],
                    "series": [],
                    "asin": "B00EXAMPLE",
                    "isbn": None,
                },
                "evidence": [
                    {"dimension": "identity", "field": "title", "contribution": 0.42},
                    {"dimension": "edition", "field": "asin", "contribution": 0.65},
                ],
            },
        }
        proposal = store.stage_proposal(report.report_id, "Warbreaker", candidate)
        return store, proposal

    def _start_server(self, store: StateStore, *, access_token: str | None = None):
        server = create_review_server(
            store,
            bind="127.0.0.1",
            port=0,
            access_token=access_token,
        )
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"

        def cleanup() -> None:
            server.shutdown()
            server.server_close()
            thread.join(2.0)

        self.addCleanup(cleanup)
        return base_url

    def test_queue_and_detail_render_candidate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, proposal = self._store_with_proposal(Path(temp_dir))
            base_url = self._start_server(store)

            with urlopen(base_url + "/", timeout=2) as response:
                queue_html = response.read().decode("utf-8")
            self.assertIn("Warbreaker", queue_html)
            self.assertIn("identity 0.960", queue_html)
            self.assertIn("edition 0.910", queue_html)

            with urlopen(base_url + f"/proposal/{proposal.proposal_id}", timeout=2) as response:
                detail_html = response.read().decode("utf-8")
            self.assertIn("Brandon Sanderson", detail_html)
            self.assertIn("B00EXAMPLE", detail_html)
            self.assertIn("Candidate evidence", detail_html)
            self.assertIn("Review state only", detail_html)

    def test_review_post_changes_only_sqlite_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "media" / "Warbreaker.m4b"
            media.parent.mkdir()
            media.write_bytes(b"unchanged-media")
            store, proposal = self._store_with_proposal(root)
            base_url = self._start_server(store)

            with urlopen(base_url + f"/proposal/{proposal.proposal_id}", timeout=2) as response:
                detail_html = response.read().decode("utf-8")
            match = re.search(r'name="csrf" value="([^"]+)"', detail_html)
            self.assertIsNotNone(match)
            csrf = match.group(1)

            body = urlencode(
                {
                    "csrf": csrf,
                    "decision": "approved",
                    "note": "Verified title, author, narrator, ASIN and duration",
                }
            ).encode("utf-8")
            request = Request(
                base_url + f"/proposal/{proposal.proposal_id}/decision",
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urlopen(request, timeout=2) as response:
                final_html = response.read().decode("utf-8")

            self.assertIn("Decision recorded", final_html)
            decided = store.get_proposal(proposal.proposal_id)
            self.assertEqual(decided.status, "approved")
            self.assertEqual(media.read_bytes(), b"unchanged-media")

    def test_invalid_csrf_is_rejected_without_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, proposal = self._store_with_proposal(Path(temp_dir))
            base_url = self._start_server(store)
            body = urlencode({"csrf": "wrong", "decision": "approved"}).encode("utf-8")
            request = Request(
                base_url + f"/proposal/{proposal.proposal_id}/decision",
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as caught:
                urlopen(request, timeout=2)
            self.assertEqual(caught.exception.code, 403)
            self.assertEqual(store.get_proposal(proposal.proposal_id).status, "pending")

    def test_access_token_is_exchanged_for_ephemeral_http_only_browser_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, _ = self._store_with_proposal(Path(temp_dir))
            token = "review-token-0123456789abcdef"
            base_url = self._start_server(store, access_token=token)

            with self.assertRaises(HTTPError) as caught:
                urlopen(base_url + "/", timeout=2)
            self.assertEqual(caught.exception.code, 401)
            login_html = caught.exception.read().decode("utf-8")
            self.assertIn("Review queue login", login_html)

            jar = http.cookiejar.CookieJar()
            opener = build_opener(HTTPCookieProcessor(jar))
            login_body = urlencode({"token": token}).encode("utf-8")
            login_request = Request(
                base_url + "/login",
                data=login_body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with opener.open(login_request, timeout=2) as response:
                queue_html = response.read().decode("utf-8")
            self.assertIn("Pending proposals", queue_html)

            session_cookies = [cookie for cookie in jar if cookie.name == "media_janitor_review_session"]
            self.assertEqual(len(session_cookies), 1)
            self.assertNotEqual(session_cookies[0].value, token)

            with opener.open(base_url + "/", timeout=2) as response:
                self.assertEqual(response.status, 200)

    def test_wrong_login_token_does_not_establish_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, _ = self._store_with_proposal(Path(temp_dir))
            base_url = self._start_server(store, access_token="review-token-0123456789abcdef")
            body = urlencode({"token": "wrong-token-0123456789"}).encode("utf-8")
            request = Request(
                base_url + "/login",
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as caught:
                urlopen(request, timeout=2)
            self.assertEqual(caught.exception.code, 401)
            self.assertIn("Invalid review token", caught.exception.read().decode("utf-8"))

    def test_non_loopback_exposure_requires_strong_access_token(self) -> None:
        with self.assertRaisesRegex(ValueError, "access token is required"):
            validate_review_exposure("0.0.0.0", None)
        with self.assertRaisesRegex(ValueError, "at least 16"):
            validate_review_exposure("0.0.0.0", "short")
        validate_review_exposure("0.0.0.0", "0123456789abcdef")
        validate_review_exposure("127.0.0.1", None)

    def test_health_endpoint_does_not_require_browser_auth(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, _ = self._store_with_proposal(Path(temp_dir))
            base_url = self._start_server(store, access_token="review-token-0123456789abcdef")
            with urlopen(base_url + "/health", timeout=2) as response:
                payload = response.read().decode("utf-8")
            self.assertIn('"status": "ok"', payload)
            self.assertNotIn("database", payload)


if __name__ == "__main__":
    unittest.main()
