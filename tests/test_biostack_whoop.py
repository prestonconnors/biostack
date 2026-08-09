import argparse
import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import biostack_whoop


class SaveTokensTests(unittest.TestCase):
    @patch.object(biostack_whoop, "load_tokens", return_value={})
    def test_token_file_is_owner_readable_only(self, _mock_load_tokens):
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = os.path.join(temp_dir, "whoop_tokens.json")
            with patch.object(biostack_whoop, "TOKEN_FILE", token_file):
                biostack_whoop.save_tokens(
                    {
                        "access_token": "access-token",
                        "refresh_token": "refresh-token",
                    }
                )

            with open(token_file) as saved_file:
                saved_tokens = json.load(saved_file)

            self.assertEqual(saved_tokens["refresh_token"], "refresh-token")
            self.assertEqual(stat.S_IMODE(os.stat(token_file).st_mode), 0o600)


class RefreshAccessTokenTests(unittest.TestCase):
    @patch.object(biostack_whoop, "save_tokens")
    @patch.object(biostack_whoop, "load_tokens")
    @patch.object(biostack_whoop.requests, "post")
    def test_refresh_requests_only_offline_scope(
        self, mock_post, mock_load_tokens, mock_save_tokens
    ):
        mock_load_tokens.return_value = {"refresh_token": "old-refresh-token"}
        response = Mock(status_code=200)
        response.json.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
        }
        mock_post.return_value = response

        token = biostack_whoop.refresh_access_token()

        self.assertEqual(token, "new-access-token")
        payload = mock_post.call_args.kwargs["data"]
        self.assertEqual(payload["scope"], "offline")
        mock_save_tokens.assert_called_once_with(response.json.return_value)

    @patch.object(biostack_whoop, "save_tokens")
    @patch.object(biostack_whoop, "load_tokens")
    @patch.object(biostack_whoop.requests, "post")
    def test_failed_refresh_does_not_save_tokens(
        self, mock_post, mock_load_tokens, mock_save_tokens
    ):
        mock_load_tokens.return_value = {"refresh_token": "old-refresh-token"}
        mock_post.return_value = Mock(status_code=400, text="invalid request")

        with self.assertRaisesRegex(Exception, "Token Refresh Failed"):
            biostack_whoop.refresh_access_token()

        mock_save_tokens.assert_not_called()


class FetchAllMetricsTests(unittest.TestCase):
    @patch.object(
        biostack_whoop,
        "ENDPOINTS",
        {"cycles": "https://example.test/developer/v2/cycle"},
    )
    @patch.object(biostack_whoop, "make_request_with_retry")
    def test_api_error_aborts_fetch_instead_of_returning_empty_data(self, mock_request):
        mock_request.return_value = Mock(status_code=500, text="server error")

        with self.assertRaisesRegex(RuntimeError, "cycles.*500"):
            biostack_whoop.fetch_all_metrics(
                biostack_whoop.datetime(2026, 7, 12),
                biostack_whoop.datetime(2026, 8, 9),
            )


class MainTests(unittest.TestCase):
    @patch.object(biostack_whoop, "upload_to_aws")
    @patch.object(biostack_whoop, "fetch_all_metrics")
    @patch.object(biostack_whoop, "get_args")
    def test_gather_failure_returns_nonzero_without_uploading(
        self, mock_get_args, mock_fetch, mock_upload
    ):
        mock_get_args.return_value = argparse.Namespace(
            start="2026-07-12", end="2026-08-09", days=28
        )
        mock_fetch.side_effect = RuntimeError("authentication failed")

        with redirect_stdout(io.StringIO()):
            exit_code = biostack_whoop.main()

        self.assertEqual(exit_code, 1)
        mock_upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
