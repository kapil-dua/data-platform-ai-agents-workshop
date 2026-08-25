"""
Test script to verify agent functionality without Streamlit
"""
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from config import Config
from agents.supervisor_agent import SupervisorAgent
from tools.databricks_tools import DatabricksJobsClient


def test_configuration():
    """Test configuration loading"""
    print("=" * 60)
    print("Testing Configuration...")
    print("=" * 60)
    
    try:
        Config.validate()
        print("✅ Configuration validated successfully")
        print(f"   - Databricks workspace: {Config.DATABRICKS_WORKSPACE_HOST}")
        print(f"   - LLM Model: {Config.DATABRICKS_MODEL_ID}")
        return True
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        return False


def test_aws_connection():
    """Test AWS connection"""
    print("\n" + "=" * 60)
    print("Testing AWS Connection...")
    print("=" * 60)
    
    try:
        databricks_client = DatabricksJobsClient()
        jobs = databricks_client.list_all_jobs()
        
        print(f"✅ Connected to AWS successfully")
        print(f"   - Found {len(jobs)} Databricks jobs")
        
        if jobs:
            print(f"   - Sample jobs: {', '.join(jobs[:3])}")
        
        return True
    except Exception as e:
        print(f"❌ AWS connection error: {e}")
        return False


def test_monitor_agent():
    """Test monitor agent"""
    print("\n" + "=" * 60)
    print("Testing Monitor Agent...")
    print("=" * 60)
    
    try:
        from agents.monitor_agent import MonitorAgent
        
        agent = MonitorAgent()
        state = {}
        
        result = agent.monitor_jobs(state)
        
        jobs_data = result.get('jobs_data', {})
        print(f"✅ Monitor agent executed successfully")
        print(f"   - Total jobs: {jobs_data.get('total_jobs', 0)}")
        print(f"   - Failed jobs: {jobs_data.get('failed_count', 0)}")
        print(f"   - Successful jobs: {jobs_data.get('successful_count', 0)}")
        
        return True
    except Exception as e:
        print(f"❌ Monitor agent error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_supervisor_workflow():
    """Test complete supervisor workflow"""
    print("\n" + "=" * 60)
    print("Testing Supervisor Workflow...")
    print("=" * 60)
    
    try:
        supervisor = SupervisorAgent()
        
        print("Running complete monitoring workflow...")
        results = supervisor.run_monitoring_workflow()
        
        print("\n✅ Workflow completed successfully!")
        print("\nResults Summary:")
        print("-" * 60)
        
        # Display results
        jobs_data = results.get('jobs_data', {})
        print(f"Total Jobs: {jobs_data.get('total_jobs', 0)}")
        print(f"Failed Jobs: {jobs_data.get('failed_count', 0)}")
        print(f"Successful Jobs: {jobs_data.get('successful_count', 0)}")
        
        print("\nMonitor Summary:")
        print(results.get('monitor_summary', 'N/A'))
        
        rca_results = results.get('rca_results', [])
        if rca_results:
            print(f"\nRCA Results: {len(rca_results)} jobs analyzed")
            for rca in rca_results[:2]:  # Show first 2
                print(f"  - {rca['job_name']}: {rca['severity']} severity")
        
        return True
    except Exception as e:
        print(f"❌ Workflow error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("ETL Monitoring Application - Test Suite")
    print("=" * 60)
    
    tests = [
        ("Configuration", test_configuration),
        ("AWS Connection", test_aws_connection),
        ("Monitor Agent", test_monitor_agent),
        ("Supervisor Workflow", test_supervisor_workflow),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"\n❌ Unexpected error in {test_name}: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    for test_name, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{test_name:.<40} {status}")
    
    total = len(results)
    passed = sum(1 for _, success in results if success)
    
    print("=" * 60)
    print(f"Total: {passed}/{total} tests passed")
    print("=" * 60)


if __name__ == "__main__":
    main()