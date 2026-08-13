from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from media_janitor.cli import main


class ReviewCliTests(unittest.TestCase):
    def test_review_server_uses_environment_token_without_printing_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"
            token = "super-secret-review-token-012345"
            stdout = StringIO()
            with patch.dict(os.environ, {"MEDIA_JANITOR_REVIEW_TOKEN": token}, clear=False):
                with patch("media_janitor.cli.serve_review_queue") as serve:
                    with redirect_stdout(stdout):
                        result = main(
                            [
                                "review-server",
                                "--state-dir",
                                str(state_dir),
                                "--bind",
                                "0.0.0.0",
                                "--port",
                                "8123",
                            ]
                        )

            self.assertEqual(result, 0)
            serve.assert_called_once_with(
                state_dir,
                bind="0.0.0.0",
                port=8123,
                access_token=token,
            )
            self.assertNotIn(token, stdout.getvalue())
            self.assertIn('"write_boundary": "review-state-only"', stdout.getvalue())

    def test_explicit_access_token_overrides_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"
            with patch.dict(os.environ, {"MEDIA_JANITOR_REVIEW_TOKEN": "environment-token-012345"}, clear=False):
                with patch("media_janitor.cli.serve_review_queue") as serve:
                    with redirect_stdout(StringIO()):
                        result = main(
                            [
                                "review-server",
                                "--state-dir",
                                str(state_dir),
                                "--access-token",
                                "explicit-token-0123456789",
                            ]
                        )

            self.assertEqual(result, 0)
            serve.assert_called_once_with(
                state_dir,
                bind="127.0.0.1",
                port=8090,
                access_token="explicit-token-0123456789",
            )


if __name__ == "__main__":
    unittest.main()
