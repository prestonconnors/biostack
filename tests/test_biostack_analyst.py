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


class SocialIntelHistoryTests(unittest.TestCase):
    def test_merges_deduplicates_and_filters_stored_posts(self):
        s3 = Mock()
        s3.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "social/social_intel_20260716.json"},
                {"Key": "social/social_intel_20260720.json"},
                {"Key": "social/social_intel_20260803.json"},
                {"Key": "social/social_intel_20260815.json"},
                {"Key": "social/social_cache.json"},
            ]
        }
        payloads = {
            "social/social_intel_20260720.json": {
                "expert_a": [
                    {"id": "too-old", "ts": "2026-07-16T23:59:59.000Z"},
                    {
                        "id": "duplicate",
                        "ts": "2026-07-18T12:00:00.000Z",
                        "content": "older copy",
                    },
                    {"id": "bad-date", "ts": "not-a-date"},
                ]
            },
            "social/social_intel_20260803.json": {
                "expert_a": [
                    {
                        "id": "duplicate",
                        "ts": "2026-07-18T12:00:00.000Z",
                        "content": "newer copy",
                    },
                    {"id": "august", "ts": "2026-08-01T10:00:00.000Z"},
                ],
                "expert_b": [
                    {"id": "end-day", "ts": "2026-08-14T23:59:59.000Z"},
                    {"id": "too-new", "ts": "2026-08-15T00:00:00.000Z"},
                ],
            },
            "social/social_intel_20260815.json": {
                "expert_b": [
                    {
                        "id": "late-collected",
                        "ts": "2026-08-14T12:00:00.000Z",
                    },
                    {"id": "still-too-new", "ts": "2026-08-15T08:00:00.000Z"},
                ]
            },
        }

        def get_object(**kwargs):
            body = Mock()
            body.read.return_value = json.dumps(payloads[kwargs["Key"]]).encode()
            return {"Body": body}

        s3.get_object.side_effect = get_object

        result = biostack_analyst.get_social_intel_for_range(
            s3,
            datetime(2026, 7, 17),
            datetime(2026, 8, 14),
        )

        self.assertEqual(
            [post["id"] for post in result["expert_a"]],
            ["august", "duplicate"],
        )
        self.assertEqual(result["expert_a"][1]["content"], "newer copy")
        self.assertEqual(
            [post["id"] for post in result["expert_b"]],
            ["end-day", "late-collected"],
        )
        self.assertEqual(
            s3.get_object.call_args_list,
            [
                call(
                    Bucket=biostack_analyst.BUCKET_NAME,
                    Key="social/social_intel_20260720.json",
                ),
                call(
                    Bucket=biostack_analyst.BUCKET_NAME,
                    Key="social/social_intel_20260803.json",
                ),
                call(
                    Bucket=biostack_analyst.BUCKET_NAME,
                    Key="social/social_intel_20260815.json",
                ),
            ],
        )

    def test_paginates_social_history_listing(self):
        s3 = Mock()
        s3.list_objects_v2.side_effect = [
            {
                "Contents": [],
                "IsTruncated": True,
                "NextContinuationToken": "next-page",
            },
            {
                "Contents": [{"Key": "social/social_intel_20260803.json"}],
                "IsTruncated": False,
            },
        ]
        body = Mock()
        body.read.return_value = json.dumps(
            {"expert": [{"id": "1", "ts": "2026-08-03T12:00:00.000Z"}]}
        ).encode()
        s3.get_object.return_value = {"Body": body}

        result = biostack_analyst.get_social_intel_for_range(
            s3,
            datetime(2026, 8, 1),
            datetime(2026, 8, 14),
        )

        self.assertEqual(result["expert"][0]["id"], "1")
        self.assertEqual(
            s3.list_objects_v2.call_args_list,
            [
                call(
                    Bucket=biostack_analyst.BUCKET_NAME,
                    Prefix="social/social_intel_",
                ),
                call(
                    Bucket=biostack_analyst.BUCKET_NAME,
                    Prefix="social/social_intel_",
                    ContinuationToken="next-page",
                ),
            ],
        )


class AnalystMainTests(unittest.TestCase):
    @patch("builtins.open", new_callable=mock_open)
    @patch.object(biostack_analyst, "load_template_string", return_value="{{DATASET}}")
    @patch.object(biostack_analyst, "get_social_intel_for_range", return_value=None)
    @patch.object(biostack_analyst, "get_latest_file_content", return_value=None)
    @patch.object(biostack_analyst, "get_s3_client")
    @patch.object(biostack_analyst, "get_args")
    def test_main_uses_requested_range_for_social_history(
        self,
        mock_get_args,
        mock_get_s3_client,
        mock_latest_file,
        mock_social_history,
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
            ],
        )
        mock_social_history.assert_called_once_with(
            s3,
            datetime(2026, 7, 12),
            datetime(2026, 8, 9),
        )


if __name__ == "__main__":
    unittest.main()
