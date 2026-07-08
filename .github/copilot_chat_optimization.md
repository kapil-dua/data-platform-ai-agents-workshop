# GitHub Copilot Chat Mode - AI Credits Optimization Guide

## Key Facts
- **Code completions & inline suggestions**: ✅ FREE (not billed)
- **Copilot Chat**: ❌ Billed in AI credits
- **Focus**: Reduce token consumption in Chat mode only

## Where Credits Are Consumed
| Feature | Billing |
|---------|---------|
| Inline code completions | ✅ FREE |
| Next edit suggestions | ✅ FREE |
| Copilot Chat in agent mode | ❌ **CREDITS USED** |

---

## Copilot Chat Configuration (`.vscode/settings.json`)

### Settings That Reduce Token Consumption

```json
"github.copilot.chat": {
  "codeAnalysis.enabled": false,
  "useEditorContext": false,
  "useEditorContextWithoutFormattingAndComments": false,
  "maxConcurrentRequests": 1,
  "commandTimeout": 5000
}
```

| Setting | Impact | Savings |
|---------|--------|---------|
| `codeAnalysis.enabled: false` | Disables automatic file scanning | 30-40% |
| `useEditorContext: false` | Prevents auto-context inclusion | 40-50% |
| `maxConcurrentRequests: 1` | One chat at a time (no parallel calls) | 50% |
| `commandTimeout: 5000` | Timeout slow requests | 10% |
| **TOTAL POTENTIAL SAVINGS** | | **60-80%** |

---

## Chat Mode Usage Patterns

### ❌ HIGH-COST Patterns (Avoid)
```
Copilot Chat Request: "Analyze my entire ETL system and generate monitoring code"
- Auto-scans entire workspace: ~10,000 tokens
- Analyzes all imports and dependencies: ~5,000 tokens
- Generates response: ~2,000 tokens
- TOTAL: ~17,000 tokens (17 AI credits)

Copilot Chat using @github or @workspace
- Includes all project context: ~8,000-15,000 tokens
- TOTAL: ~15,000+ tokens per request
```

### ✅ LOW-COST Patterns (Use)
```
Copilot Chat: "Add error handling to this function: [paste 15 lines]"
- Explicit code: ~300 tokens
- Request text: ~100 tokens
- Generates response: ~800 tokens
- TOTAL: ~1,200 tokens (~1 AI credit)

Copilot Chat: "Modify this implementation to use retry logic: [paste code]"
- Reusing/modifying: ~1,000-1,500 tokens
- TOTAL: ~1,500 tokens (~1.5 AI credits)
```

---

## Best Practices for Agent Mode

### 1. **Never Use Auto-Context** (80-90% savings per request)
```
❌ DON'T: Use @github, @workspace, or let Copilot auto-scan
✅ DO: Manually copy-paste specific code snippets (10-50 lines max)

Example:
- @workspace approach: 15,000 tokens
- Manual paste approach: 1,200 tokens
- **SAVINGS: 91%**
```

### 2. **Explicit & Minimal Requests** (50% savings)
```
❌ "Improve this code and add features"
✅ "Add try-except blocks to this function"

❌ "Help me build a monitoring system"
✅ "Generate a function to check Glue job status"
```

### 3. **Break Complex Tasks into Sequential Chats** (30-40% savings)
```
Instead of 1 Chat: "Design, implement, and test ETL monitor"
Use 3 Chats:
1. "Design: Create class structure for ETL monitor"
2. "Implement: Add these methods [specific list]"
3. "Test: Write unit tests for the monitor class"

Benefit: Can reuse responses across chats, close tabs between tasks
```

### 4. **Reuse & Modify Instead of Regenerate** (50-80% savings)
```
Cost of regeneration: 800-1,500 tokens per request
Cost of modification: 200-400 tokens

Workflow:
1. Get response from Chat (1,000 tokens)
2. Copy it into editor
3. Later: Ask Chat to "modify this code to add feature X" (300 tokens)
TOTAL: 1,300 tokens for 2 tasks

vs

1. Generate code (1,000 tokens)
2. Generate modified version (1,000 tokens)
TOTAL: 2,000 tokens

**SAVINGS: 35%**
```

### 5. **Close Chat Tabs Between Tasks** (20% savings)
```
❌ Keep multiple chat tabs open = context re-processed per interaction
✅ Close chat tab after extracting response = fresh start for new task

Each interaction in an old chat re-processes the entire conversation history
```
