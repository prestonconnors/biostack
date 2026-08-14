import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_ALL = REPO_ROOT / "run_all.sh"


class RunAllRetryTests(unittest.TestCase):
    def run_with_stubbed_python(self, function_body, attempts):
        with tempfile.TemporaryDirectory() as temp_dir:
            calls_file = Path(temp_dir) / "calls.txt"
            marker_file = Path(temp_dir) / "marker"
            harness = f"""
python() {{
    printf '%s\\n' "$1" >> "$BIOSTACK_TEST_CALLS"
    {function_body}
}}
export -f python
exec "$1" --template templates/preston_coach.txt --days 2
"""
            env = {
                **os.environ,
                "BIOSTACK_RETRY_ATTEMPTS": str(attempts),
                "BIOSTACK_RETRY_DELAY_SECONDS": "0",
                "BIOSTACK_TEST_CALLS": str(calls_file),
                "BIOSTACK_TEST_MARKER": str(marker_file),
            }
            result = subprocess.run(
                ["bash", "-c", harness, "bash", str(RUN_ALL)],
                cwd="/",
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            calls = calls_file.read_text().splitlines()
            return result, calls

    def test_failed_step_is_retried_and_pipeline_continues(self):
        result, calls = self.run_with_stubbed_python(
            """
if [[ "$1" == "biostack_whoop.py" && ! -e "$BIOSTACK_TEST_MARKER" ]]; then
    touch "$BIOSTACK_TEST_MARKER"
    return 23
fi
return 0
""",
            attempts=3,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls.count("biostack_whoop.py"), 2)
        self.assertEqual(calls.count("biostack_social.py"), 1)
        self.assertIn("Attempt 1/3 failed with exit code 23", result.stderr)
        self.assertIn("Recovered on attempt 2/3", result.stdout)

    def test_exhausted_step_stops_pipeline_with_original_exit_code(self):
        result, calls = self.run_with_stubbed_python(
            """
if [[ "$1" == "biostack_whoop.py" ]]; then
    return 42
fi
return 0
""",
            attempts=2,
        )

        self.assertEqual(result.returncode, 42)
        self.assertEqual(calls, ["biostack_whoop.py", "biostack_whoop.py"])
        self.assertIn("Failed after 2 attempt(s)", result.stderr)


if __name__ == "__main__":
    unittest.main()
