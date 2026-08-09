import argparse
import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest.mock import Mock, call, mock_open, patch

import biostack_analyst


class LatestFileContentTests(unittest.TestCase):
    def test_lists_only_files_matching_filename_prefix(self):
        s3 = Mock()
        s3.list_objects_v2.return_value = {
            "Contents": [
                {
                    "Key": "social/social_intel_20260808.json",
                    "LastModified": datetime(2026, 8, 8, tzinfo=timezone.utc),
                },
                {
                    "Key": "social/social_intel_20260809.json",
                    "LastModified": datetime(2026, 8, 9, tzinfo=timezone.utc),
                },
            ]
        }
        body = Mock()
        body.read.return_value = json.dumps({"posts": ["latest"]}).encode()
        s3.get_object.return_value = {"Body": body}

        result = biostack_analyst.get_latest_file_content(
            s3,
            "social",
            filename_prefix="social_intel_",
        )

        s3.list_objects_v2.assert_called_once_with(
            Bucket=biostack_analyst.BUCKET_NAME,
            Prefix="social/social_intel_",
        )
        s3.get_object.assert_called_once_with(
            Bucket=biostack_analyst.BUCKET_NAME,
            Key="social/social_intel_20260809.json",
        )
        self.assertEqual(result, {"posts": ["latest"]})


class AnalystMainTests(unittest.TestCase):
    @patch("builtins.open", new_callable=mock_open)
    @patch.object(biostack_analyst, "load_template_string", return_value="{{DATASET}}")
    @patch.object(biostack_analyst, "get_latest_file_content", return_value=None)
    @patch.object(biostack_analyst, "get_s3_client")
    @patch.object(biostack_analyst, "get_args")
    def test_main_requests_only_social_intel_files(
        self,
        mock_get_args,
        mock_get_s3_client,
        mock_latest_file,
        _mock_template,
        _mock_file,
    ):
        mock_get_args.return_value = argparse.Namespace(
            start="2026-07-12",
            end="2026-08-09",
            days=28,
            template="templates/preston_coach.txt",
        )
        s3 = mock_get_s3_client.return_value

        with redirect_stdout(io.StringIO()):
            biostack_analyst.main()

        self.assertEqual(
            mock_latest_file.call_args_list,
            [
                call(s3, "whoop"),
                call(s3, "nutrition"),
                call(s3, "vitals"),
                call(
                    s3,
                    biostack_analyst.SOCIAL_OUTPUT_PREFIX,
                    filename_prefix=biostack_analyst.SOCIAL_INTEL_FILENAME_PREFIX,
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
