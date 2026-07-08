"""
Streamlit Web Interface for ETL Monitoring Application
"""
import streamlit as st
import time
from datetime import datetime
from config import Config
from agents.supervisor_agent import SupervisorAgent
from tools.aws_tools import AWSGlueClient


# Page configuration
st.set_page_config(
    page_title="ETL Job Monitoring Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

MODEL_ID = Config.OLLAMA_MODEL_ID if Config.MODEL_TO_USE == "ollama" else Config.GROQ_MODEL_ID if Config.MODEL_TO_USE == "groq" else "None"

def initialize_session_state():
    """Initialize session state variables"""
    if 'monitoring_complete' not in st.session_state:
        st.session_state.monitoring_complete = False
    if 'last_run_time' not in st.session_state:
        st.session_state.last_run_time = None
    if 'results' not in st.session_state:
        st.session_state.results = None
    if 'auto_refresh' not in st.session_state:
        st.session_state.auto_refresh = False


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
    st.title("🔍 ETL Data Platform: AI Agents")
    st.markdown("---")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric(
            label="🤖 Active Agents",
            value="3",
            delta="Supervisor + 2 Workers"
        )
    
    with col2:
        if st.session_state.last_run_time:
            st.metric(
                label="⏱️ Last Run (UTC)",
                value=st.session_state.last_run_time.strftime("%Y-%m-%d %H:%M:%S")
            )
        else:
            st.metric(label="⏱️ Last Run (UTC)", value="Never")
    
    with col3:
        st.metric(
            label="🔧 LLM Model",
            value=MODEL_ID
        )


def display_sidebar():
    """Display sidebar with controls"""
    with st.sidebar:
        st.header("⚙️ Control Panel")
        
        st.subheader("Monitoring Options")
        
        # Manual trigger
        if st.button("▶️ Run Monitoring Now", type="primary", use_container_width=True):
            st.session_state.monitoring_complete = False
            st.rerun()
        
        st.markdown("---")
        
        # Auto-refresh toggle
        auto_refresh = st.checkbox(
            "🔄 Auto-refresh",
            value=st.session_state.auto_refresh,
            help=f"Automatically refresh every {Config.REFRESH_INTERVAL} seconds"
        )
        st.session_state.auto_refresh = auto_refresh
        
        if auto_refresh:
            refresh_interval = st.slider(
                "Refresh Interval (seconds)",
                min_value=60,
                max_value=600,
                value=Config.REFRESH_INTERVAL,
                step=30
            )
            st.info(f"Next refresh in {refresh_interval} seconds")
        
        st.markdown("---")
        
        # Agent Information
        st.subheader("🤖 Agent Architecture")
        
        with st.expander("Supervisor Agent", expanded=False):
            st.write("**Role:** Workflow Coordinator")
            st.write("**Tasks:**")
            st.write("- Orchestrates agent execution")
            st.write("- Routes tasks to worker agents")
            st.write("- Generates final reports")
        
        with st.expander("Monitor Agent", expanded=False):
            st.write("**Role:** Job Status Monitoring")
            st.write("**Tasks:**")
            st.write("- Tracks Configured job runs")
            st.write("- Identifies failed jobs")
            st.write("- Summarizes job statistics")
        
        with st.expander("RCA Agent", expanded=False):
            st.write("**Role:** Root Cause Analysis")
            st.write("**Tasks:**")
            st.write("- Analyzes CloudWatch logs")
            st.write("- Identifies failure patterns")
            st.write("- Provides recommendations")
        
        st.markdown("---")
        
        # System info
        st.subheader("ℹ️ System Info")
        st.text(f"AWS Region: {Config.AWS_REGION}")
        st.text(f"Model: {Config.MODEL_TO_USE} ({MODEL_ID})")
        
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


def run_monitoring():
    """Execute the monitoring workflow"""
    try:
        with st.spinner("🔄 Initializing agents..."):
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
        results = supervisor.run_monitoring_workflow()
        
        # status_text.text("📝 Supervisor Agent: Generating final report...")
        # progress_bar.progress(100)
        # time.sleep(0.5)
        
        # Clear progress indicators
        progress_bar.empty()
        status_text.empty()
        
        # Store results
        st.session_state.results = results
        st.session_state.monitoring_complete = True
        st.session_state.last_run_time = datetime.now()
        
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
    #monitor_summary = results.get('monitor_summary', 'No summary available')
    # monitor_summary = results.get('jobs_data', 'No summary available')
    # st.info(monitor_summary)

    # Jobs Data Table
    jobs_data = results.get('jobs_data', {})
    
    if 'all_jobs' in jobs_data and jobs_data['all_jobs']:
        # Convert jobs list to table format
        import pandas as pd
        jobs_df = pd.DataFrame(jobs_data['all_jobs'])
        st.dataframe(jobs_df, use_container_width=True)
    else:
        st.info("No job details available")
    
    st.markdown("---")
    
    # RCA Results
    rca_results = results.get('rca_results', [])
    
    if rca_results:
        # st.subheader("🔧 Root Cause Analysis")
        
        # # RCA Summary
        # rca_summary = results.get('rca_summary', '')
        # if rca_summary:
        #     st.warning(rca_summary)

        # st.markdown("---")
        
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
    else:
        st.success("✅ No failed jobs detected. All systems operational!")
    
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
    
    # Run monitoring if not complete
    if not st.session_state.monitoring_complete:
        run_monitoring()
    
    # Display results
    display_results()
    
    # Auto-refresh logic
    if st.session_state.auto_refresh and st.session_state.monitoring_complete:
        time.sleep(Config.REFRESH_INTERVAL)
        st.session_state.monitoring_complete = False
        st.rerun()


if __name__ == "__main__":
    main()