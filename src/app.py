"""
Streamlit Web Interface for ETL Monitoring Application
"""
import streamlit as st
import time
from datetime import datetime
from config.config import Config
from agents.supervisor_agent import SupervisorAgent
from utils.aws_utils import AWSGlueClient


# Page configuration
st.set_page_config(
    page_title="ETL Job Monitoring Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)


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
    st.title("🔍 Multi-Agent ETL Monitoring Dashboard")
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
                label="⏱️ Last Run",
                value=st.session_state.last_run_time.strftime("%H:%M:%S")
            )
        else:
            st.metric(label="⏱️ Last Run", value="Never")
    
    with col3:
        st.metric(
            label="🔧 LLM Model",
            value=Config.GROQ_MODEL
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
            st.write("- Tracks AWS Glue job runs")
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
        st.text(f"Region: {Config.AWS_REGION}")
        st.text(f"Model: {Config.GROQ_MODEL}")


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
        
        status_text.text("📝 Supervisor Agent: Generating final report...")
        progress_bar.progress(100)
        time.sleep(0.5)
        
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
    st.subheader("📊 Job Status Overview")
    
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
    st.subheader("🔍 Monitor Agent Summary")
    monitor_summary = results.get('monitor_summary', 'No summary available')
    st.info(monitor_summary)
    
    st.markdown("---")
    
    # RCA Results
    rca_results = results.get('rca_results', [])
    
    if rca_results:
        st.subheader("🔧 Root Cause Analysis")
        
        # RCA Summary
        rca_summary = results.get('rca_summary', '')
        if rca_summary:
            st.warning(rca_summary)
        
        st.markdown("---")
        
        # Detailed RCA for each failed job
        st.subheader("📋 Detailed Analysis")
        
        for idx, rca in enumerate(rca_results):
            with st.expander(f"❌ {rca['job_name']} - {rca['severity']} Severity", expanded=(idx == 0)):
                col1, col2 = st.columns([1, 2])
                
                with col1:
                    st.write("**Job Details:**")
                    st.text(f"Run ID: {rca['run_id']}")
                    st.text(f"Severity: {rca['severity']}")
                    if rca['error_message']:
                        st.text(f"Error: {rca['error_message'][:100]}...")
                
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
    
    # Final Report
    st.subheader("📄 Executive Report")
    final_report = results.get('final_report', 'No report available')
    st.markdown(final_report)
    
    # Download report option
    st.download_button(
        label="📥 Download Full Report",
        data=final_report,
        file_name=f"etl_monitoring_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
        mime="text/plain"
    )


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