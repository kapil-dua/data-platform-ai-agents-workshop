"""
Streamlit Web Interface for Data Platform AI Agents
"""
import streamlit as st
import time
from datetime import datetime
import config
from config import Config
from agents.supervisor_agent import SupervisorAgent


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
    if 'auto_refresh' not in st.session_state:
        st.session_state.auto_refresh = False
    if 'refresh_interval' not in st.session_state:
        st.session_state.refresh_interval = max(Config.REFRESH_INTERVAL, 1)
    if 'workflow_task' not in st.session_state:
        st.session_state.workflow_task = "monitor_analyze_incident"


def respond_to_incident_review(approved: bool) -> bool:
    """Resume the paused LangGraph workflow with the reviewer's decision."""
    run_id = st.session_state.results.get("workflow_run_id")
    if not run_id:
        st.error("Unable to resume incident review: workflow run ID is missing")
        return False
    try:
        with st.spinner("Resuming workflow..."):
            supervisor = SupervisorAgent()
            st.session_state.results = supervisor.resume_incident_review(run_id, approved)
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
        [data-testid="stMetricLabel"] p {
            font-size: 1.15rem;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.35rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("🔍 Data Platform: AI Agents")
    st.markdown("---")
    
    col1, col2, col3 = st.columns(3)

    with col1:
            st.metric(
                label="🔧 Data Platform",
                value=Config.DATABRICKS_WORKSPACE_HOST
            )

    with col2:
        st.metric(
            label="🤖 Active Agents",
            value="3",
            delta="Supervisor + 3 Workers"
        )
    
    with col3:
        if st.session_state.last_run_time:
            st.metric(
                label="⏱️ Last Run (UTC)",
                value=st.session_state.last_run_time.strftime("%Y-%m-%d %H:%M:%S")
            )
        else:
            st.metric(label="⏱️ Last Run (UTC)", value="Never")
    

def display_sidebar():
    """Display sidebar with controls"""
    with st.sidebar:
        st.header("⚙️ Control Panel")
        
        st.subheader("Traige Options")

        st.session_state.workflow_task = st.selectbox(
            "Workflow",
            options=[
                "monitor",
                "monitor_and_analyze",
                "monitor_analyze_incident",
            ],
            index=[
                "monitor",
                "monitor_and_analyze",
                "monitor_analyze_incident",
            ].index(st.session_state.workflow_task),
        )
        
        # Manual trigger
        review_pending = bool(
            st.session_state.results
            and st.session_state.results.get("__interrupt__")
        )
        if st.button(
            "▶️ Run Monitoring Now",
            type="primary",
            width="stretch",
            disabled=review_pending,
        ):
            st.session_state.monitoring_requested = True
            st.session_state.monitoring_complete = False
            st.rerun()
        if review_pending:
            st.caption("Approve or reject the pending incidents before starting another run.")
        
        st.markdown("---")
        
        # Auto-refresh toggle
        was_auto_refresh = st.session_state.auto_refresh
        auto_refresh = st.checkbox(
            "🔄 Auto-refresh",
            value=st.session_state.auto_refresh,
            help=f"Automatically refresh every {st.session_state.refresh_interval} seconds"
        )
        st.session_state.auto_refresh = auto_refresh

        if auto_refresh and not was_auto_refresh:
            st.session_state.monitoring_requested = True
            st.session_state.monitoring_complete = False
        
        if auto_refresh:
            st.session_state.refresh_interval = st.slider(
                "Refresh Interval (seconds)",
                min_value=1,
                max_value=600,
                value=st.session_state.refresh_interval,
                step=1
            )
            st.info(f"Next refresh in {st.session_state.refresh_interval} seconds")
        
        st.markdown("---")
        
        # Agent Information
        st.subheader("🤖 Agent Architecture")
        
        with st.expander("Supervisor Agent", expanded=False):
            st.write("**Role:** Workflow Coordinator")
            st.write("**Tasks:**")
            st.write("- Orchestrates multi-agents workflow execution")
            st.write("- Coordinates specialized traige worker agents")
        
        with st.expander("Monitor Agent", expanded=False):
            st.write("**Role:** Job Status Monitoring")
            st.write("**Tasks:**")
            st.write("- Tracks Configured job runs")
            st.write("- Identifies failed jobs")
        
        with st.expander("RCA Agent", expanded=False):
            st.write("**Role:** Root Cause Analysis")
            st.write("**Tasks:**")
            st.write("- Analyzes failed jobs runs")
            st.write("- Provides Root Cause & Recommendations")

        with st.expander("Incident Agent", expanded=False):
                    st.write("**Role:** Incident Management")
                    st.write("**Tasks:**")
                    st.write("- Create Jira tickets for failed jobs")
                    st.write("- Attach RCA analysis to tickets")
        
        st.markdown("---")
        
        # System info
        st.subheader("ℹ️ Model Info")
        st.text(f"Model provider: {Config.MODEL_PROVIDER}")
        st.text(f"Model ID: {MODEL_ID}")
        
        # Observability info
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
            # Triggers a rerun of the script, picking up any new .env changes
            st.rerun()


def run_monitoring():
    """Execute the monitoring workflow"""
    try:
        st.session_state.last_run_time = datetime.now()

        with st.spinner("🔄 Initializing agents workflow..."):
            supervisor = SupervisorAgent()
        
        # Create progress placeholders
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # Run workflow with progress updates
        status_text.text("📊 Monitor Agent: Checking job statuses...")
        progress_bar.progress(33)
        time.sleep(0.5)
        
        status_text.text("🔍 RCA Agent: Analyzing failed jobs...")
        progress_bar.progress(66)
        
        # Execute workflow
        results = supervisor.run_monitoring_workflow(
            task=st.session_state.workflow_task,
        )
        
        # Clear progress indicators
        progress_bar.empty()
        status_text.empty()
        
        # Store results
        st.session_state.results = results
        st.session_state.monitoring_complete = True
        st.session_state.monitoring_requested = False
        
        st.success("✅ Monitoring workflow completed successfully!")
        
    except Exception as e:
        st.error(f"❌ Error during monitoring: {str(e)}")
        st.exception(e)


def display_results():
    """Display monitoring results"""
    if not st.session_state.results:
        st.info("👆 Click 'Run Monitoring Now' to start monitoring your ETL jobs")
        return
    
    results = st.session_state.results

    execution_log = results.get("execution_log", [])
    workflow_graph = results.get("workflow_graph")
    if execution_log or workflow_graph:
        st.subheader("Traige Workflow Execution")
        graph_column, messages_column = st.columns([1, 1.2])
        with graph_column:
            if workflow_graph:
                st.caption("Executed path highlighted in green")
                st.graphviz_chart(workflow_graph, width="stretch", height=360)
        with messages_column:
            for message in execution_log:
                st.write(message)
    
    # Overall metrics
    st.subheader("📊 Jobs Monitoring Status")
    
    jobs_data = results.get('jobs_data', {})
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            label="Total Jobs",
            value=jobs_data.get('total_jobs', 0),
            delta=None
        )
    
    with col2:
        st.metric(
            label="✅ Successful",
            value=jobs_data.get('successful_count', 0),
            delta=None,
            delta_color="normal"
        )
    
    with col3:
        failed_count = jobs_data.get('failed_count', 0)
        st.metric(
            label="❌ Failed",
            value=failed_count,
            delta=f"{failed_count} issues" if failed_count > 0 else "No issues",
            delta_color="inverse"
        )
    
    with col4:
        st.metric(
            label="🔄 Running",
            value=jobs_data.get('running_count', 0),
            delta=None
        )
    
    st.markdown("---")
    
    # Monitor Summary
    st.subheader("🔍 Monitor Agent - Result")

    # Jobs Data Table
    jobs_data = results.get('jobs_data', {})
    
    if 'all_jobs' in jobs_data and jobs_data['all_jobs']:
        # Convert jobs list to table format
        import pandas as pd
        jobs_df = pd.DataFrame(jobs_data['all_jobs'])
        st.dataframe(jobs_df, width="stretch")
    else:
        st.info("No job details available")
    
    st.markdown("---")
    
    # RCA Results
    rca_results = results.get('rca_results', [])
    
    if rca_results:

        # Detailed RCA for each failed job
        st.subheader("📋 RCA Agent - Result")
        
        for idx, rca in enumerate(rca_results):
            with st.expander(f"❌ {rca['job_name']} - {rca['severity']} Severity", expanded=(idx == 0)):
                col1, col2 = st.columns([1, 2])
                
                with col1:
                    st.write("**Job Details:**")
                    st.text(f"Run ID: {rca['run_id']}")
                    st.text(f"Severity: {rca['severity']}")
                    if rca['error_message']:
                        st.text(f"Error: {rca['error_message'][:200]}...")
                
                with col2:
                    st.write("**Root Cause:**")
                    st.write(rca['root_cause'])
                
                if rca.get('recommendations'):
                    st.write("**Recommendations:**")
                    for rec in rca['recommendations']:
                        st.write(f"• {rec}")

    incident_results = results.get("incident_results", [])
    pending_review = results.get("__interrupt__", [])
    if pending_review:
        review_payload = pending_review[0].value
        st.subheader("Human Review: Jira Incident Creation")
        st.warning(f"{len(review_payload['incidents'])} incident(s) are awaiting approval. No Jira issues have been created yet.")
        for index, incident in enumerate(review_payload["incidents"]):
            with st.expander(
                f"{incident.get('job_name', 'Unknown job')} - {incident.get('severity', 'Unspecified')} severity",
                expanded=(index == 0),
            ):
                st.json(incident)
        approve_column, reject_column, _ = st.columns([1, 1, 5])
        with approve_column:
            if st.button("Approve and Create All", type="primary", key="approve_incidents"):
                if respond_to_incident_review(approved=True):
                    st.rerun()
        with reject_column:
            if st.button("Reject All", key="reject_incidents"):
                if respond_to_incident_review(approved=False):
                    st.rerun()

    if incident_results:
        st.subheader("Incident Agent - Result")
        st.dataframe(incident_results, width="stretch")
    
    st.markdown("---")


def main():
    """Main application logic"""
    initialize_session_state()
    
    # Validate configuration
    if not validate_configuration():
        st.stop()
    
    # Display header and sidebar
    display_header()
    display_sidebar()
    
    # Main content area
    st.markdown("---")
    
    # Run monitoring only after an explicit or scheduled request
    if st.session_state.monitoring_requested and not st.session_state.monitoring_complete:
        run_monitoring()
    
    # Display results
    display_results()
    
    # Auto-refresh logic
    awaiting_review = bool(
        st.session_state.results
        and st.session_state.results.get("__interrupt__")
    )
    if st.session_state.auto_refresh and st.session_state.monitoring_complete and not awaiting_review:
        time.sleep(st.session_state.refresh_interval)
        st.session_state.monitoring_requested = True
        st.session_state.monitoring_complete = False
        st.rerun()


if __name__ == "__main__":
    main()