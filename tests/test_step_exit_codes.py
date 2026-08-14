import argparse
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import biostack_drive
import biostack_nutrition
import biostack_social
import biostack_vitals


class StepExitCodeTests(unittest.TestCase):
    @patch.object(biostack_social, "get_args")
    @patch.object(biostack_social, "HANDLES", [])
    def test_social_configuration_failure_returns_nonzero(self, mock_get_args):
        mock_get_args.return_value = argparse.Namespace()

        with redirect_stdout(io.StringIO()):
            exit_code = biostack_social.main()

        self.assertEqual(exit_code, 1)

    @patch.object(
        biostack_nutrition,
        "download_mynetdiary_years",
        side_effect=RuntimeError("temporary download failure"),
    )
    @patch.object(biostack_nutrition, "get_args")
    def test_nutrition_download_failure_returns_nonzero(
        self, mock_get_args, _mock_download
    ):
        mock_get_args.return_value = argparse.Namespace(
            start="2026-08-01", end="2026-08-14", days=28
        )

        with redirect_stdout(io.StringIO()):
            exit_code = biostack_nutrition.main()

        self.assertEqual(exit_code, 1)

    @patch.object(
        biostack_vitals,
        "authenticate_google",
        side_effect=RuntimeError("temporary auth failure"),
    )
    @patch.object(biostack_vitals, "get_args")
    def test_vitals_api_failure_returns_nonzero(
        self, mock_get_args, _mock_authenticate
    ):
        mock_get_args.return_value = argparse.Namespace(
            start="2026-08-01", end="2026-08-14", days=28
        )

        with redirect_stdout(io.StringIO()):
            exit_code = biostack_vitals.main()

        self.assertEqual(exit_code, 1)

    @patch.object(biostack_drive, "FOLDER_ID", None)
    def test_drive_configuration_failure_returns_nonzero(self):
        with redirect_stdout(io.StringIO()):
            exit_code = biostack_drive.main()

        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
