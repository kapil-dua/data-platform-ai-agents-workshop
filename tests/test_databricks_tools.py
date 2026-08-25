"""Offline tests for the Databricks Jobs API client."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from tools.databricks_tools import DatabricksJobsClient


class DatabricksJobsClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = DatabricksJobsClient()
        self.client.workspace_client = Mock()

    def test_list_all_jobs_follows_pagination(self) -> None:
        self.client.workspace_client.jobs.list.return_value = iter(["job-1", "job-2"])

        self.assertEqual(["job-1", "job-2"], self.client.list_all_jobs())

    def test_get_all_jobs_status_normalizes_run_state(self) -> None:
        job = SimpleNamespace(job_id=7, settings=SimpleNamespace(name="daily-load"))
        run = SimpleNamespace(
            run_id=42, run_name="daily-load", start_time=1000, end_time=5000,
            run_page_url="", state=SimpleNamespace(
                life_cycle_state="TERMINATED", result_state="FAILED", state_message="task failed"
            )
        )
        self.client.workspace_client.jobs.list.return_value = iter([job])
        self.client.workspace_client.jobs.list_runs.return_value = iter([run])

        status = self.client.get_all_jobs_status()[0]

        self.assertEqual("daily-load", status["job_name"])
        self.assertEqual("FAILED", status["status"])
        self.assertEqual(4, status["execution_time"])
        self.assertEqual("task failed", status["error_message"])

    def test_get_job_logs_combines_run_output(self) -> None:
        self.client.workspace_client.jobs.get_run.return_value = SimpleNamespace(tasks=[])
        self.client.workspace_client.jobs.get_run_output.return_value = SimpleNamespace(
            error="Command failed", error_trace="Traceback...",
            notebook_output=SimpleNamespace(result="bad input"),
        )

        logs = self.client.get_job_logs("daily-load", 42)

        self.assertIn("Command failed", logs)
        self.assertIn("Traceback...", logs)
        self.assertIn("bad input", logs)

    def test_get_job_logs_uses_each_task_run_for_multi_task_job(self) -> None:
        self.client.workspace_client.jobs.get_run.return_value = SimpleNamespace(
            tasks=[SimpleNamespace(run_id=101), SimpleNamespace(run_id=102)]
        )
        self.client.workspace_client.jobs.get_run_output.side_effect = [
            SimpleNamespace(error="task one failed", error_trace="", notebook_output=None),
            SimpleNamespace(error="task two failed", error_trace="", notebook_output=None),
        ]

        logs = self.client.get_job_logs("daily-load", 42)

        self.assertIn("task one failed", logs)
        self.assertIn("task two failed", logs)
        self.client.workspace_client.jobs.get_run_output.assert_any_call(101)
        self.client.workspace_client.jobs.get_run_output.assert_any_call(102)


if __name__ == "__main__":
    unittest.main()