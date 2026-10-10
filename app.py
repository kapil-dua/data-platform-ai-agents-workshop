"""
Streamlit Web Interface for Data Platform AI Agents
"""
import streamlit as st
import time
from datetime import datetime
import config
from config import Config
from agents.supervisor_agent import SupervisorAgent
from utils.durable_memory import WorkflowStore
import ticker_manager


# ── Demo helper jobs that support FORCE_SUCCESS parameter ─────────────────────
FORCE_SUCCESS_JOBS = [
    "etl_raw_to_cleansed_customers",
    "etl_cleansed_to_conformed_revenue",
    "etl_cleansed_to_conformed_inventory",
]


def run_jobs_with_force_success() -> dict[str, str]:
    """Update FORCE_SUCCESS=true on failing demo jobs and trigger them."""
    import concurrent.futures
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service import jobs as jobs_sdk

    client = WorkspaceClient(
        host=Config.DATABRICKS_WORKSPACE_HOST,
        token=Config.DATABRICKS_TOKEN,
    )

    def _run_with_force_success(job_name: str) -> tuple[str, str]:
        jobs = list(client.jobs.list(name=job_name))
        if not jobs:
            return job_name, "NOT_FOUND"

        job_id = jobs[0].job_id

        # Update job parameters to set FORCE_SUCCESS=true
        job_details = client.jobs.get(job_id=job_id)
        tasks = job_details.settings.tasks or []
        updated_tasks = []
        for task in tasks:
            nb_task = task.notebook_task
            if nb_task:
                params = dict(nb_task.base_parameters or {})
                params["FORCE_SUCCESS"] = "true"
                updated_tasks.append(jobs_sdk.Task(
                    task_key=task.task_key,
                    notebook_task=jobs_sdk.NotebookTask(
                        notebook_path=nb_task.notebook_path,
                        base_parameters=params,
                    ),
                ))
            else:
                updated_tasks.append(task)

        client.jobs.update(
            job_id=job_id,
            new_settings=jobs_sdk.JobSettings(tasks=updated_tasks),
        )

        # Trigger the run
        run = client.jobs.run_now(job_id=job_id)
        run_id = run.run_id

        # Wait for completion
        while True:
            time.sleep(8)
            details = client.jobs.get_run(run_id=run_id)
            lc = getattr(details.state.life_cycle_state, "value", str(details.state.life_cycle_state))
            if lc in {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}:
                rs = getattr(details.state.result_state, "value", str(details.state.result_state))
                return job_name, rs

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(_run_with_force_success, j): j for j in FORCE_SUCCESS_JOBS}
        for f in concurrent.futures.as_completed(futures):
            jname, rs = f.result()
            results[jname] = rs

    return results


def _update_force_success_param(force_value: str) -> None:
    """Update FORCE_SUCCESS parameter on all demo jobs without triggering a run.

    Args:
        force_value: "true" to make jobs succeed, "false" to revert to failing
    """
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service import jobs as jobs_sdk

    client = WorkspaceClient(
        host=Config.DATABRICKS_WORKSPACE_HOST,
        token=Config.DATABRICKS_TOKEN,
    )

    for job_name in FORCE_SUCCESS_JOBS:
        jobs = list(client.jobs.list(name=job_name))
        if not jobs:
            continue
        job_id = jobs[0].job_id
        job_details = client.jobs.get(job_id=job_id)
        tasks = job_details.settings.tasks or []
        updated_tasks = []
        for task in tasks:
            nb_task = task.notebook_task
            if nb_task:
                params = dict(nb_task.base_parameters or {})
                params["FORCE_SUCCESS"] = force_value
                updated_tasks.append(jobs_sdk.Task(
                    task_key=task.task_key,
                    notebook_task=jobs_sdk.NotebookTask(
                        notebook_path=nb_task.notebook_path,
                        base_parameters=params,
                    ),
                ))
            else:
                updated_tasks.append(task)
        client.jobs.update(
            job_id=job_id,
            new_settings=jobs_sdk.JobSettings(tasks=updated_tasks),
        )


# Page configuration
st.set_page_config(
    page_title="Data Platform AI Agents",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)


def initialize_session_state():
    """Initialize session state variables"""
    # Initialize all session state keys once on first load
    if 'monitoring_complete' not in st.session_state:
        st.session_state.monitoring_complete = False
    if 'monitoring_requested' not in st.session_state:
        st.session_state.monitoring_requested = False
    if 'last_run_time' not in st.session_state:
        st.session_state.last_run_time = None
    if 'results' not in st.session_state:
        st.session_state.results = None
    if 'ui_refresh_interval' not in st.session_state:
        st.session_state.ui_refresh_interval = 30
    if 'ui_auto_refresh' not in st.session_state:
        st.session_state.ui_auto_refresh = False
    if 'workflow_task' not in st.session_state:
        st.session_state.workflow_task = "monitor_analyze_incident"
    if 'mode' not in st.session_state:
        st.session_state.mode = "manual"  # "ticker" | "manual"
    if 'monitoring_running' not in st.session_state:
        st.session_state.monitoring_running = False


def respond_to_incident_review(decisions: list[dict]) -> bool:
    """Resume the paused LangGraph workflow with per-incident review decisions."""
    run_id = st.session_state.results.get("workflow_run_id")
    if not run_id:
        st.error("Unable to resume incident review: workflow run ID is missing")
        return False
    try:
        with st.spinner("Resuming workflow..."):
            supervisor = SupervisorAgent()
            st.session_state.results = supervisor.resume_incident_review(run_id, decisions)
        return True
    except Exception as exc:
        st.error(f"Unable to resume incident review: {exc}")
        st.exception(exc)
        return False


def validate_configuration():
    """Validate configuration and show warnings if needed"""
    try:
        Config.validate()
        return True
    except ValueError as e:
        st.error(f"⚠️ Configuration Error: {str(e)}")
        st.info("Please configure your environment variables in the .env file")
        return False


def display_header():
    """Render the top-of-page header, CSS tweaks, and platform metrics."""
    st.markdown(
        """
        <style>
        [data-testid="stMetricLabel"] p { font-size: 0.78rem; }
        [data-testid="stMetricValue"]   { font-size: 0.9rem;  }
        [data-testid="stMetric"]        { padding-top: 0.2rem; padding-bottom: 0.2rem; }
        .block-container { padding-top: 2.5rem !important; }
        .stGraphVizChart svg { max-height: 320px; width: 100% !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("### 🔍 Data Platform: AI Agents", unsafe_allow_html=False)
    st.markdown("---")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(label="🔧 Data Platform", value=Config.DATABRICKS_WORKSPACE_HOST)
    with col2:
        st.metric(label="🤖 Active Agents", value="4", delta="Supervisor + 4 Workers")
    with col3:
        if st.session_state.last_run_time:
            st.metric(
                label="⏱️ Last Run (UTC)",
                value=st.session_state.last_run_time.strftime("%Y-%m-%d %H:%M:%S"),
            )
        else:
            st.metric(label="⏱️ Last Run (UTC)", value="Never")


def _render_agent_architecture():
    """Render the four agent architecture expanders inside the sidebar."""
    st.subheader("🤖 Agent Architecture")
    with st.expander("Supervisor Agent", expanded=False):
        st.write("**Role:** ReAct Workflow Coordinator")
        st.write("- Orchestrates 4 specialised worker agents")
        st.write("- Uses LLM reasoning to decide which agent to invoke next")
        st.write("- Logs reasoning to execution log")
    with st.expander("Worker 1 — Monitor Agent", expanded=False):
        st.write("**Role:** Job Status Monitoring")
        st.write("- Tracks all Databricks job runs via SDK")
        st.write("- Identifies failed jobs and surfaces error messages")
    with st.expander("Worker 2 — RCA Fan-Out", expanded=False):
        st.write("**Role:** Parallel RCA Dispatcher")
        st.write("- Uses LangGraph Send API to dispatch one RCA per failed job")
        st.write("- All jobs analysed simultaneously (not sequentially)")
        st.write("- Results merged via Annotated reducer (Option 2 — Shared Memory)")
    with st.expander("Worker 3 — RCA Evaluator", expanded=False):
        st.write("**Role:** Quality Gate (Evaluator-Optimizer)")
        st.write("- Scores each RCA on Clarity, Actionability, Completeness (1-10)")
        st.write("- Checks whether DAB context and UC lineage were used correctly")
        st.write("- Enforces WHAT + WHERE + ACCESS in every fix step")
        st.write("- Retries below-threshold RCAs with targeted per-criterion feedback")
    with st.expander("Worker 4 — Incident Agent", expanded=False):
        st.write("**Role:** Incident Management")
        st.write("- Pauses for human review before creating any ticket (HITL)")
        st.write("- Supports per-incident approve/reject, severity override, context note")
        st.write("- Creates Jira tickets via Atlassian Rovo MCP")


def display_sidebar():
    """Render the sidebar control panel: run mode, ticker controls, agent info, and model info."""
    model_id = (
        Config.GROQ_MODEL_ID if Config.MODEL_PROVIDER == "groq" else
        Config.OLLAMA_MODEL_ID if Config.MODEL_PROVIDER == "ollama" else
        Config.DATABRICKS_MODEL_ID if Config.MODEL_PROVIDER == "databricks" else
        "None"
    )

    store = WorkflowStore()

    with st.sidebar:
        st.header("⚙️ Control Panel")

        # ── Mode toggle ────────────────────────────────────────────────────
        st.subheader("🕹️ Run Mode")
        mode = st.radio(
            "How should the workflow run?",
            options=["ticker", "manual"],
            format_func=lambda m: "⏱️ Background Ticker (auto)" if m == "ticker" else "▶️ Manual (on demand)",
            index=0 if st.session_state.mode == "ticker" else 1,
            help=(
                "Ticker: a separate ticker.py process runs on a schedule and the UI just reads results.\n"
                "Manual: click the button to run the workflow directly from the UI."
            ),
        )
        st.session_state.mode = mode

        st.markdown("---")

        # ── Ticker schedule config + controls ──────────────────────────────
        if mode == "ticker":
            st.subheader("📅 Ticker Schedule")
            current = store.get_ticker_schedule()

            ticker_mode = st.selectbox(
                "Schedule type",
                options=["interval", "cron"],
                index=0 if current.get("mode", "interval") == "interval" else 1,
                format_func=lambda m: "Every N minutes" if m == "interval" else "Daily at fixed time (UTC)",
            )

            if ticker_mode == "interval":
                interval_min = st.number_input(
                    "Run every (minutes)",
                    min_value=1,
                    max_value=1440,
                    value=int(current.get("interval_min", 30)),
                    step=5,
                )
                cron_time = current.get("cron_time", "06:00")
            else:
                cron_time = st.text_input(
                    "Run at (HH:MM UTC)",
                    value=current.get("cron_time", "06:00"),
                    help="24-hour format, UTC. e.g. 06:30",
                )
                interval_min = int(current.get("interval_min", 30))

            ticker_task = st.selectbox(
                "Workflow",
                options=["monitor", "monitor_and_analyze", "monitor_analyze_incident"],
                index=["monitor", "monitor_and_analyze", "monitor_analyze_incident"].index(
                    current.get("task", "monitor_and_analyze")
                ),
            )

            st.markdown("---")

            # ── Ticker status + start / stop ───────────────────────────────
            running = ticker_manager.is_running()
            pid     = ticker_manager.get_pid()

            if running:
                st.success(f"🟢 Ticker running (PID {pid})")
            else:
                st.warning("🔴 Ticker is not running")

            start_col, stop_col = st.columns(2)
            with start_col:
                if st.button(
                    "▶ Start Ticker",
                    type="primary",
                    width='stretch',
                    disabled=running,
                ):
                    store.save_ticker_schedule(
                        mode=ticker_mode,
                        interval_min=int(interval_min),
                        cron_time=cron_time,
                        task=ticker_task,
                    )
                    msg = ticker_manager.start(
                        mode=ticker_mode,
                        interval_min=int(interval_min),
                        cron_time=cron_time,
                        task=ticker_task,
                    )
                    st.info(msg)
                    st.rerun()

            with stop_col:
                if st.button(
                    "⏹ Stop Ticker",
                    width='stretch',
                    disabled=not running,
                ):
                    msg = ticker_manager.stop()
                    st.info(msg)
                    st.rerun()

            if st.button("🔄 Apply New Schedule", width='stretch', disabled=not running):
                ticker_manager.stop()
                store.save_ticker_schedule(
                    mode=ticker_mode,
                    interval_min=int(interval_min),
                    cron_time=cron_time,
                    task=ticker_task,
                )
                msg = ticker_manager.start(
                    mode=ticker_mode,
                    interval_min=int(interval_min),
                    cron_time=cron_time,
                    task=ticker_task,
                )
                st.info(msg)
                st.rerun()

            st.markdown("---")

            # ── Ticker log ─────────────────────────────────────────────────
            with st.expander("📋 Ticker Log (last 30 lines)", expanded=False):
                st.code(ticker_manager.get_log(30), language="text")
                if st.button("🔃 Refresh Log"):
                    st.rerun()

            st.markdown("---")
            st.subheader("🔄 UI Auto-Refresh")
            st.caption("The UI polls SQLite for new ticker results.")
            ui_auto_refresh = st.checkbox(
                "Auto-refresh UI",
                value=st.session_state.ui_auto_refresh,
            )
            st.session_state.ui_auto_refresh = ui_auto_refresh
            if ui_auto_refresh:
                st.session_state.ui_refresh_interval = st.slider(
                    "Poll interval (seconds)",
                    min_value=5,
                    max_value=300,
                    value=st.session_state.ui_refresh_interval,
                    step=5,
                )
                st.info(f"Refreshing every {st.session_state.ui_refresh_interval}s")

        # ── Manual mode controls ───────────────────────────────────────────
        else:
            review_pending = bool(
                st.session_state.results
                and st.session_state.results.get("__interrupt__")
            )
            if st.button(
                "▶️ Run Monitoring Now",
                type="primary",
                width='stretch',
                disabled=review_pending or st.session_state.monitoring_running,
            ):
                st.session_state.workflow_task = "monitor_analyze_incident"
                st.session_state.monitoring_requested = True
                st.session_state.monitoring_complete = False
                st.rerun()
            if review_pending:
                st.caption("Approve or reject the pending incidents before starting another run.")

            st.markdown("")

            # ── Demo: force all failing jobs to succeed ────────────────────
            with st.expander("🎭 Demo Controls", expanded=False):
                st.caption(
                    "Force the 3 failing demo jobs to succeed — useful for demonstrating "
                    "the workflow when no failures are found."
                )
                col1, col2 = st.columns(2)
                with col1:
                    if st.button(
                        "✅ Force Success",
                        width="stretch",
                        disabled=st.session_state.monitoring_running,
                        help="Sets FORCE_SUCCESS=true and runs all 3 failing jobs",
                    ):
                        with st.spinner("Running jobs with FORCE_SUCCESS=true..."):
                            try:
                                results = run_jobs_with_force_success()
                                all_ok = all(rs in ("SUCCESS", "SUCCEEDED") for rs in results.values())
                                if all_ok:
                                    st.success("✅ All jobs succeeded! Click 'Run Monitoring Now' to see the success workflow.")
                                else:
                                    for jname, rs in results.items():
                                        icon = "✅" if rs in ("SUCCESS", "SUCCEEDED") else "❌"
                                        st.write(f"{icon} `{jname.split('/')[-1]}`: {rs}")
                            except Exception as e:
                                st.error(f"Error: {e}")
                with col2:
                    if st.button(
                        "❌ Revert to Failures",
                        width="stretch",
                        disabled=st.session_state.monitoring_running,
                        help="Sets FORCE_SUCCESS=false on all 3 jobs — next run will fail again",
                    ):
                        with st.spinner("Reverting FORCE_SUCCESS=false..."):
                            try:
                                _update_force_success_param("false")
                                st.success("↩️ Reverted. Next job run will fail as expected.")
                            except Exception as e:
                                st.error(f"Error: {e}")

        st.markdown("---")

        # ── Agent architecture ─────────────────────────────────────────────
        _render_agent_architecture()

        st.markdown("---")
        st.subheader("ℹ️ Model Info")
        st.text(f"Provider : {Config.MODEL_PROVIDER}")
        st.text(f"Model ID : {model_id}")

        st.markdown("---")
        st.subheader("📊 Observability")
        if Config.LANGFUSE_ENABLED:
            st.success("✅ Langfuse Tracing Enabled")
            st.caption("All agent execution traces are being captured")
            if st.button("🔗 View Traces in Langfuse"):
                st.info(f"Go to: {Config.LANGFUSE_HOST}")
        else:
            st.info("⚪ Langfuse Tracing Disabled")

        if st.button("Restart Streamlit"):
            st.rerun()


def load_ticker_results():
    """Read the latest ticker result from SQLite and update session state."""
    store = WorkflowStore()
    result = store.get_latest_result()
    if result:
        saved_at = result.get("_saved_at", "unknown")
        if st.session_state.results is None or result.get("workflow_run_id") != (
            st.session_state.results or {}
        ).get("workflow_run_id"):
            st.session_state.results = result
            try:
                st.session_state.last_run_time = datetime.strptime(
                    saved_at, "%Y-%m-%d %H:%M:%S"
                )
            except Exception:
                pass


def run_monitoring():
    """Execute the monitoring workflow and stream live status updates to the UI."""
    st.session_state.monitoring_running = True
    try:
        st.session_state.last_run_time = datetime.now()
        supervisor = SupervisorAgent()

        status_header     = st.empty()
        graph_placeholder = st.empty()
        jobs_placeholder  = st.empty()
        rca_placeholder   = st.empty()

        status_header.info("⏳ Workflow starting...")
        rca_in_progress: dict = {}

        for chunk in supervisor.stream_monitoring_workflow(
            task=st.session_state.workflow_task,
        ):
            node  = chunk["node"]
            state = chunk["state"]

            # Update live graph after every node
            workflow_graph = state.get("workflow_graph")
            if workflow_graph:
                with graph_placeholder.container():
                    st.caption("Executed path highlighted in green")
                    st.graphviz_chart(workflow_graph, width='stretch')

            if node == "monitor":
                jobs_data    = state.get("jobs_data", {})
                failed_jobs  = state.get("failed_jobs", [])
                failed_count = jobs_data.get("failed_count", len(failed_jobs))
                total        = jobs_data.get("total_jobs", 0)
                status_header.success(f"📊 Monitor complete — {total} jobs checked, {failed_count} failed")
                if failed_jobs:
                    with jobs_placeholder.container():
                        st.markdown("**Failed jobs found — starting RCA:**")
                        for j in failed_jobs:
                            st.markdown(f"- ❌ `{j['job_name']}`")
                    rca_in_progress = {j["job_name"]: "⏳ queued" for j in failed_jobs}

            elif node == "rca_fan_out":
                status_header.info("🔍 RCA Fan-out — dispatching parallel analysis...")

            elif node == "rca_subgraph":
                rca_results = state.get("rca_results", [])
                for r in rca_results:
                    score  = r.get("eval_score")
                    passed = r.get("eval_passed")
                    iters  = r.get("eval_iterations", 1)
                    if score is not None:
                        icon = "✅" if passed else f"🔄 retry ({iters})"
                        rca_in_progress[r["job_name"]] = f"{icon} Score: {score:.1f}/10"
                    else:
                        rca_in_progress[r["job_name"]] = "✅ RCA done — evaluating..."
                with rca_placeholder.container():
                    st.markdown("**RCA Progress:**")
                    for jn, s in rca_in_progress.items():
                        st.markdown(f"- `{jn}` — {s}")

            elif node == "rca_evaluator":
                status_header.info("📐 All RCAs evaluated")

            elif node == "__interrupt__":
                status_header.warning("🧑‍⚖️ Workflow paused — human review required")
                st.session_state.results = state
                st.session_state.monitoring_complete = True
                st.session_state.monitoring_requested = False
                st.session_state.monitoring_running = False
                graph_placeholder.empty(); jobs_placeholder.empty(); rca_placeholder.empty()
                st.rerun()
                return

            elif node == "__end__":
                st.session_state.results = state
                st.session_state.monitoring_complete = True
                st.session_state.monitoring_requested = False
                st.session_state.monitoring_running = False
                status_header.empty(); graph_placeholder.empty()
                jobs_placeholder.empty(); rca_placeholder.empty()
                st.success("✅ Workflow completed!")
                st.rerun()
                return

    except Exception as e:
        st.session_state.monitoring_running = False
        st.error(f"❌ Error during monitoring: {str(e)}")
        st.exception(e)


def display_results():
    """Render the full results panel: workflow graph, job metrics, RCA details, and incident review."""
    if not st.session_state.results:
        if st.session_state.mode == "ticker":
            st.info(
                "⏳ Waiting for the ticker to complete its first run.\n\n"
                "Start the ticker in a separate terminal:\n```\npython ticker.py\n```"
            )
        else:
            st.info("👆 Click 'Run Monitoring Now' to start monitoring your ETL jobs")
        return

    results = st.session_state.results

    # Show ticker source badge
    saved_at = results.get("_saved_at")
    if saved_at:
        st.caption(f"📡 Results from background ticker — last updated: {saved_at} UTC")

    execution_log = results.get("execution_log", [])
    workflow_graph = results.get("workflow_graph")
    if execution_log or workflow_graph:
        st.subheader("Triage Workflow Execution")
        graph_column, messages_column = st.columns([1, 1.2])
        with graph_column:
            if workflow_graph:
                st.caption("Executed path highlighted in green")
                st.graphviz_chart(workflow_graph, width="stretch", height=360)
        with messages_column:
            for message in execution_log:
                st.write(message)

    # ── Token consumption summary ──────────────────────────────────────────
    token_usage = results.get("token_usage", {})
    if token_usage and token_usage.get("total_tokens", 0) > 0:
        with st.expander(
            f"💰 Token Usage — {token_usage['total_tokens']:,} tokens "
            f"(~${token_usage['total_cost_usd']:.4f} USD)",
            expanded=False,
        ):
            nodes = token_usage.get("nodes", {})
            if nodes:
                cols = st.columns(len(nodes))
                for col, (node_name, usage) in zip(cols, nodes.items()):
                    with col:
                        st.metric(
                            label=f"🔹 {node_name}",
                            value=f"{usage['total_tokens']:,}",
                            delta=f"${usage['estimated_cost_usd']:.4f}",
                            delta_color="off",
                        )
                        st.caption(
                            f"In: {usage['prompt_tokens']:,} | "
                            f"Out: {usage['completion_tokens']:,} | "
                            f"Calls: {usage['calls']}"
                        )

    st.subheader("📊 Jobs Monitoring Status")
    jobs_data = results.get("jobs_data", {})
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(label="Total Jobs", value=jobs_data.get("total_jobs", 0))
    with col2:
        st.metric(label="✅ Successful", value=jobs_data.get("successful_count", 0))
    with col3:
        failed_count = jobs_data.get("failed_count", 0)
        st.metric(
            label="❌ Failed",
            value=failed_count,
            delta=f"{failed_count} issues" if failed_count > 0 else "No issues",
            delta_color="inverse",
        )
    with col4:
        st.metric(label="🔄 Running", value=jobs_data.get("running_count", 0))

    st.markdown("---")
    st.subheader("🔍 Monitor Agent - Result")
    if "all_jobs" in jobs_data and jobs_data["all_jobs"]:
        import pandas as pd
        st.dataframe(pd.DataFrame(jobs_data["all_jobs"]), width='stretch')
    else:
        st.info("No job details available")

    st.markdown("---")
    rca_results = results.get("rca_results", [])
    if rca_results:
        st.subheader("📋 RCA Agent - Result")
        for idx, rca in enumerate(rca_results):
            eval_score = rca.get("eval_score")
            eval_label = f" · Quality Score: {eval_score:.1f}/10" if eval_score else ""
            eval_iters = rca.get("eval_iterations")
            iter_label = f" · {eval_iters} iteration(s)" if eval_iters else ""
            with st.expander(
                f"❌ {rca['job_name']} — {rca['severity']} Severity{eval_label}{iter_label}",
                expanded=(idx == 0),
            ):
                col1, col2 = st.columns([1, 2])
                with col1:
                    st.write("**Job Details:**")
                    st.text(f"Run ID: {rca['run_id']}")
                    st.text(f"Severity: {rca['severity']}")
                    if rca.get("error_message"):
                        err = str(rca['error_message'])
                        if err and err.lower() not in ("n/a", "", "check run details") \
                                and "workload failed" not in err.lower():
                            st.write("**Error:**")
                            st.code(err, language=None)

                    if eval_score is not None:
                        st.write("**Evaluator Scores:**")
                        breakdown = rca.get("eval_scores_breakdown", {})
                        passed_eval = rca.get("eval_passed", False)
                        score_color = "green" if passed_eval else "orange"
                        st.markdown(
                            f"Overall: :{score_color}[**{eval_score:.1f}/10**] "
                            f"({'✅ Passed' if passed_eval else '⚠️ Below threshold'})"
                        )
                        if breakdown:
                            st.text(f"Clarity:       {breakdown.get('clarity', 'N/A')}/10")
                            st.text(f"Actionability: {breakdown.get('actionability', 'N/A')}/10")
                            st.text(f"Completeness:  {breakdown.get('completeness', 'N/A')}/10")
                        if eval_iters:
                            st.text(f"Iterations:    {eval_iters}")
                        if not passed_eval:
                            for fb_key, fb_label in [
                                ("_eval_clarity_feedback",      "🔤 Clarity feedback"),
                                ("_eval_actionability_feedback","🔧 Actionability feedback"),
                                ("_eval_completeness_feedback", "📋 Completeness feedback"),
                            ]:
                                if rca.get(fb_key):
                                    st.caption(f"**{fb_label}:** {rca[fb_key]}")
                with col2:
                    full = rca.get("_full_response") or rca.get("root_cause", "")
                    st.write(full)

    incident_results = results.get("incident_results", [])
    pending_review = results.get("__interrupt__", [])
    if pending_review:
        review_payload = pending_review[0].value
        incidents      = review_payload["incidents"]

        st.subheader("🧑‍⚖️ Human Review: Incident Creation")
        st.warning(
            f"{len(incidents)} incident(s) awaiting your review. "
            "Approve, adjust severity, and add context before submitting."
        )

        SEVERITIES = ["Critical", "High", "Medium", "Low"]

        with st.form("incident_review_form"):
            per_incident: list[dict] = []

            for idx, incident in enumerate(incidents):
                severity = incident.get("severity", "Medium")
                icon = "🔴" if severity in ("Critical", "High") else "🟡"

                st.markdown(f"#### {icon} {incident.get('job_name', 'Unknown')} — {severity}")

                col_info, col_controls = st.columns([2, 1])

                with col_info:
                    st.write("**Root Cause:**")
                    st.write(incident.get("root_cause", "N/A"))
                    if incident.get("recommendations"):
                        st.write("**Recommendations:**")
                        for rec in incident["recommendations"]:
                            st.write(f"• {rec}")

                with col_controls:
                    decision = st.radio(
                        "Decision",
                        options=["🟢 Approve", "🔴 Decline"],
                        index=0,
                        key=f"approve_{idx}_{incident.get('run_id')}",
                        horizontal=False,
                    )
                    approved = decision == "🟢 Approve"
                    severity_override = st.selectbox(
                        "Severity",
                        options=SEVERITIES,
                        index=SEVERITIES.index(severity) if severity in SEVERITIES else 1,
                        key=f"sev_{idx}_{incident.get('run_id')}",
                        help="Override the LLM-assigned severity",
                    )
                    context_note = st.text_area(
                        "Context note (added to ticket)",
                        placeholder="e.g. Related to yesterday's deployment",
                        key=f"ctx_{idx}_{incident.get('run_id')}",
                        height=80,
                    )

                per_incident.append({
                    "run_id":            incident.get("run_id"),
                    "approved":          approved,
                    "severity_override": severity_override if severity_override != severity else None,
                    "context_note":      context_note.strip(),
                })

                if idx < len(incidents) - 1:
                    st.divider()

            st.markdown("")
            approved_count = sum(1 for d in per_incident if d["approved"])
            declined_count = len(per_incident) - approved_count
            st.caption(f"{approved_count} approved · {declined_count} declined")

            submitted = st.form_submit_button(
                f"Submit Decisions",
                type="primary",
                width='stretch',
            )

        if submitted:
            if respond_to_incident_review(per_incident):
                st.rerun()

    if incident_results:
        st.subheader("Incident Agent - Result")
        st.dataframe(incident_results, width='stretch')

    st.markdown("---")


def main():
    """Main application logic"""
    initialize_session_state()

    if not validate_configuration():
        st.stop()

    display_header()
    display_sidebar()
    st.markdown("---")

    # In ticker mode: load latest results from SQLite
    if st.session_state.mode == "ticker":
        load_ticker_results()
    # In manual mode: run on demand
    elif st.session_state.monitoring_requested and not st.session_state.monitoring_complete:
        run_monitoring()

    display_results()

    # UI auto-refresh in ticker mode (polls SQLite for new results)
    awaiting_review = bool(
        st.session_state.results and st.session_state.results.get("__interrupt__")
    )
    if (
        st.session_state.mode == "ticker"
        and st.session_state.ui_auto_refresh
        and not awaiting_review
    ):
        time.sleep(st.session_state.ui_refresh_interval)
        st.rerun()


if __name__ == "__main__":
    main()
