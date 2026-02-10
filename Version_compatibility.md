# Library Versions and Compatibility

## Updated Versions (February 2026)

This document details the latest compatible versions of all dependencies for the ETL Monitoring Application.

### Core Dependencies

| Package | Version | Released | Notes |
|---------|---------|----------|-------|
| **langchain** | 1.2.8 | Dec 9, 2025 | Main LangChain library |
| **langchain-core** | 1.1.2 | Latest | Core interfaces and base classes |
| **langgraph** | 1.0.7 | Jan 22, 2026 | Graph-based agent orchestration |
| **langchain-groq** | 1.1.2 | Feb 2, 2026 | Groq API integration for LangChain |

### AWS SDK

| Package | Version | Released | Notes |
|---------|---------|----------|-------|
| **boto3** | 1.42.40 | Feb 2, 2026 | AWS SDK for Python |
| **botocore** | 1.42.40 | Feb 2, 2026 | Low-level AWS interface (auto-installed with boto3) |

### Web Framework

| Package | Version | Released | Notes |
|---------|---------|----------|-------|
| **streamlit** | 1.54.0 | Latest | Interactive web application framework |

### Utilities

| Package | Version | Released | Notes |
|---------|---------|----------|-------|
| **python-dotenv** | 1.0.1 | Latest | Environment variable management |
| **pydantic** | 2.10.5 | Latest | Data validation and settings management |

## Python Version Requirements

- **Minimum Python Version**: 3.10
- **Recommended Python Version**: 3.11 or 3.12
- **Maximum Python Version**: 3.14 (as of February 2026)

## Version Compatibility Notes

### LangChain Ecosystem

The current LangChain ecosystem uses version 1.x for stability:

- `langchain==1.2.8` is compatible with `langchain-core>=1.1.0,<2.0.0`
- `langgraph==1.0.7` requires `langchain-core>=0.3.0`
- `langchain-groq==1.1.2` requires `langchain-core>=1.1.0,<2.0.0`

All versions are compatible with each other in the configuration provided.

### Groq API

- The latest `langchain-groq` version (1.1.2) supports the newest Groq API features
- Model string for llama-3.1-8b-instant remains: `"llama-3.1-8b-instant"`
- The Groq underlying library (`groq==1.0.0`) is auto-installed as a dependency

### AWS Boto3

- Boto3 version 1.42.40 supports Python 3.10+
- Python 3.8 support ended on April 22, 2025
- Python 3.9 support will end on April 29, 2026
- Latest API features for AWS Glue and CloudWatch are included

### Streamlit

- Streamlit 1.54.0 includes the latest features as of February 2026:
  - Session-scoped connections for Snowflake
  - Experimental Starlette/ASGI support
  - Improved authentication features
  - Enhanced UI components

## Breaking Changes from Original Versions

### From langchain 0.1.0 to 1.2.8

**Major Changes:**
1. **Import paths** may have changed for some modules
2. **Callback handling** has been refactored
3. **Memory management** has improved interfaces
4. **Type hints** are more comprehensive

**Code Compatibility:**
Most code should work without changes, but you may need to:
- Update import statements if using internal modules
- Review deprecated warnings
- Update callback implementations if using custom callbacks

### From langgraph 0.0.26 to 1.0.7

**Major Changes:**
1. **StateGraph API** has stabilized (no breaking changes expected)
2. **Checkpointing** interface is more robust
3. **Node and edge definitions** remain backward compatible

**Code Compatibility:**
The code in this project is fully compatible. The main improvements are:
- Better error messages
- Performance optimizations
- Enhanced debugging capabilities

### From streamlit 1.29.0 to 1.54.0

**Major Changes:**
1. **Session state** management improvements
2. **New components** added (st.space, st.auth, etc.)
3. **Performance optimizations** for large datasets

**Code Compatibility:**
All existing Streamlit code in this project works without modification. New features are opt-in.

## Dependency Installation

### Standard Installation

```bash
pip install -r requirements.txt
```

### Installation with Specific Versions

```bash
# Install exact versions (recommended for production)
pip install \
  langchain==1.2.8 \
  langchain-core==1.1.2 \
  langgraph==1.0.7 \
  langchain-groq==1.1.2 \
  boto3==1.42.40 \
  streamlit==1.54.0 \
  python-dotenv==1.0.1 \
  pydantic==2.10.5
```

### Virtual Environment Setup

```bash
# Create virtual environment
python -m venv .venv

# Activate (Linux/Mac)
source .venv/bin/activate

# Activate (Windows)
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Testing Compatibility

After updating to these versions, run the test script to ensure everything works:

```bash
python test_agents.py
```

This will verify:
- Configuration loading
- AWS connectivity
- LangChain/LangGraph functionality
- Groq API integration
- Complete workflow execution

## Troubleshooting

### Common Issues

**Issue 1: Import Errors**
```
ImportError: cannot import name 'X' from 'langchain'
```
**Solution**: Some imports moved between versions. Check the [LangChain migration guide](https://python.langchain.com/docs/versions/migrating_chains/).

**Issue 2: Pydantic Validation Errors**
```
ValidationError: X validation error for Y
```
**Solution**: Pydantic v2 has stricter validation. Ensure your data models match expected types.

**Issue 3: Streamlit Deprecation Warnings**
```
DeprecationWarning: st.beta_X is deprecated
```
**Solution**: Update to non-beta versions of components (e.g., `st.beta_columns` → `st.columns`).

## Version Update Strategy

To keep dependencies up to date:

1. **Monitor releases** for security patches
2. **Test updates** in development environment first
3. **Update incrementally** (one major version at a time)
4. **Check changelogs** for breaking changes

### Automated Updates

You can use tools like `pip-review` or `pip-upgrader`:

```bash
# Install pip-review
pip install pip-review

# Check for updates
pip-review

# Upgrade all packages interactively
pip-review --interactive
```

## License Compatibility

All packages use permissive licenses compatible with commercial use:

- LangChain/LangGraph: MIT License
- Boto3: Apache License 2.0
- Streamlit: Apache License 2.0
- Python-dotenv: BSD License
- Pydantic: MIT License

## Security Considerations

- All versions are from PyPI's verified publishers
- Boto3 and Streamlit have active security maintenance
- Regular updates recommended for security patches
- Use `pip audit` or `safety` to check for known vulnerabilities

```bash
# Check for known vulnerabilities
pip install safety
safety check
```

## Changelog Summary

### Key Improvements in Updated Versions

**LangChain 1.2.8:**
- Improved streaming support
- Better error handling
- Enhanced type safety
- Performance optimizations

**LangGraph 1.0.7:**
- Stable 1.0 API
- Production-ready checkpointing
- Better visualization tools
- Improved debugging

**Streamlit 1.54.0:**
- Enhanced authentication
- Better session management
- New UI components
- Performance improvements

**Boto3 1.42.40:**
- Latest AWS API support
- Improved pagination
- Better error messages
- Python 3.14 support

## References

- [LangChain Documentation](https://python.langchain.com/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Boto3 Documentation](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html)
- [Streamlit Documentation](https://docs.streamlit.io/)
- [Groq Documentation](https://console.groq.com/docs)

---

**Last Updated**: February 6, 2026
**Compatible with**: Python 3.10, 3.11, 3.12, 3.13, 3.14