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


# Page configuration
st.set_page_config(
    page_title="Data Platform AI Agents",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

MODEL_ID = (
    Config.OLLAMA_MODEL_ID if Config.MODEL_PROVIDER == "ollama" else
    Config.GROQ_MODEL_ID if Config.MODEL_PROVIDER == "groq" else
    Config.DATABRICKS_MODEL_ID if Config.MODEL_PROVIDER == "databricks" else
    "None"
)


def initialize_session_state():
    """Initialize session state variables"""
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
    """Display application header"""
    st.markdown(
        """
        <style>
        [data-testid="stMetricLabel"] p { font-size: 1.15rem; }
        [data-testid="stMetricValue"]   { font-size: 1.35rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("🔍 Data Platform: AI Agents")
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


def display_sidebar():
    """Display sidebar with controls"""
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
                    use_container_width=True,
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
                    use_container_width=True,
                    disabled=not running,
                ):
                    msg = ticker_manager.stop()
                    st.info(msg)
                    st.rerun()

            if st.button("🔄 Apply New Schedule", use_container_width=True, disabled=not running):
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
                use_container_width=True,
                disabled=review_pending,
            ):
                st.session_state.workflow_task = "monitor_analyze_incident"
                st.session_state.monitoring_requested = True
                st.session_state.monitoring_complete = False
                st.rerun()
            if review_pending:
                st.caption("Approve or reject the pending incidents before starting another run.")

        st.markdown("---")

        # ── Agent architecture ─────────────────────────────────────────────
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
            st.write("- Results merged via Annotated reducer (Option 3 — Shared Memory)")
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

        st.markdown("---")
        st.subheader("ℹ️ Model Info")
        st.text(f"Provider : {Config.MODEL_PROVIDER}")
        st.text(f"Model ID : {MODEL_ID}")

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


def run_monitoring():
    """Execute the monitoring workflow directly from the UI (manual mode)."""
    try:
        st.session_state.last_run_time = datetime.now()

        with st.spinner("🔄 Initialising agents workflow..."):
            supervisor = SupervisorAgent()

        progress_bar = st.progress(0)
        status_text = st.empty()

        status_text.text("📊 Monitor Agent: Checking job statuses...")
        progress_bar.progress(33)
        time.sleep(0.5)

        status_text.text("🔍 RCA Agent: Analysing failed jobs...")
        progress_bar.progress(66)

        results = supervisor.run_monitoring_workflow(task=st.session_state.workflow_task)

        progress_bar.empty()
        status_text.empty()

        st.session_state.results = results
        st.session_state.monitoring_complete = True
        st.session_state.monitoring_requested = False

        st.success("✅ Monitoring workflow completed successfully!")

    except Exception as e:
        st.error(f"❌ Error during monitoring: {str(e)}")
        st.exception(e)


def load_ticker_results() -> None:
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


def display_results():
    """Display monitoring results"""
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
        st.dataframe(pd.DataFrame(jobs_data["all_jobs"]), use_container_width=True)
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
                        st.text(f"Error: {str(rca['error_message'])[:200]}...")

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
                        # Show per-criterion evaluator feedback if not passed
                        if not passed_eval:
                            for fb_key, fb_label in [
                                ("_eval_clarity_feedback",      "🔤 Clarity feedback"),
                                ("_eval_actionability_feedback","🔧 Actionability feedback"),
                                ("_eval_completeness_feedback", "📋 Completeness feedback"),
                            ]:
                                if rca.get(fb_key):
                                    st.caption(f"**{fb_label}:** {rca[fb_key]}")
                with col2:
                    st.write("**Root Cause:**")
                    st.write(rca["root_cause"])

                if rca.get("recommendations"):
                    st.write("**Recommendations:**")
                    for rec in rca["recommendations"]:
                        st.write(f"• {rec}")

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
                    approved = st.checkbox(
                        "✅ Approve for ticket creation",
                        value=True,
                        key=f"approve_{idx}_{incident.get('run_id')}",
                    )
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
            st.caption(f"{approved_count} of {len(incidents)} incident(s) marked for creation")

            submit_col, reject_col, _ = st.columns([1, 1, 4])
            with submit_col:
                submitted = st.form_submit_button(
                    f"✅ Submit ({approved_count} approved)",
                    type="primary",
                )
            with reject_col:
                rejected_all = st.form_submit_button("❌ Reject All")

        # Handle form submission outside the form block
        if submitted:
            if respond_to_incident_review(per_incident):
                st.rerun()
        elif rejected_all:
            all_rejected = [{**d, "approved": False} for d in per_incident]
            if respond_to_incident_review(all_rejected):
                st.rerun()

    if incident_results:
        st.subheader("Incident Agent - Result")
        st.dataframe(incident_results, use_container_width=True)

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
