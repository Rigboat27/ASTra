# ASTra: 

> Omni-Language Code Review SAST & AST-Driven A2A Sentry - Real-time $O(n^x)$ Complexity & Injection Analysis


**ASTra** (Abstract Syntax Tree Review Assistant) is an elite, multi-language SAST (Static Application Security Testing) agent built for the Nasiko platform. Unlike standard LLM reviewers, ASTra utilizes a **Tree-Sitter AST engine** to deeply parse code structures before analysis, providing high-precision detection of security vulnerabilities, logic bugs, and performance bottlenecks.

* * *

## Key Features

- **GitHub Integration**: Native support for fetching and auditing remote source files via the GitHub Contents API.
- **Tree-sitter AST Analysis**: Generates a full syntax tree, complexity metrics, and data-flow constraints to provide context-aware reviews.
<img width="955" height="677" alt="image" src="https://github.com/user-attachments/assets/abdfb947-e4ad-4c54-b485-a57986fb7ff0" />

- **Omni-Language Support**: Structural analysis for **C, C++, Python, and Java**.
- **Strict JSON Output**: Reports are delivered in a rigid JSON schema, including status, overview, analysis summary, and hardened patches.

* * *
---

##  Project Structure

```text
src/
├── __main__.py               # Server entry point; defines AgentCard and AgentSkills
├── code_analysis_agent.py     # Agent persona; defines strict JSON protocol and system prompts
├── code_analysis_toolset.py   # Implementation of the 4 core analysis tools
├── tree_maker.py              # Tree-Sitter pipeline; handles AST, IR, and data-flow
└── openai_agent_executor.py   # OpenAI-based task executor for A2A communication
Dockerfile
docker-compose.yml
pyproject.toml
AgentCard.json                 # Nasiko A2A agent card
```
***
## A2A & Nasiko Compliance

ASTra is built to be first in class in the **Agent-to-Agent (A2A)** ecosystem. It adheres to the following compliance standards:

- **Discovery**: Exposes a standardized `AgentCard` and `AgentSkill` set for platform-wide discovery.
    
- **Transport**: Uses the `A2AStarletteApplication` to handle incoming JSON-RPC 2.0 requests over HTTP.
    
- **Asynchronous Processing**: Implements `TaskUpdater` to provide real-time status updates (e.g., "Executing analyze_code_with_ast...") back to the platform.
    
- **Identity**: Dynamically reads `OPENAI_API_KEY` and `GITHUB_TOKEN` from the Nasiko environment at runtime.
    

* * *

## GitHub Integration

The `get_code_from_github` tool is the primary entry point for remote audits. It connects to the GitHub REST API to perform high-fidelity content retrieval.

### Request Lifecycle

1.  **Tool Invocation**: The agent identifies the `repo`, `path`, and `branch` from user input.
2.  **API Handshake**: ASTra sends an authenticated request to `api.github.com`.
3.  **Data Recovery**: The tool extracts and decodes the **Base64** payload returned by GitHub.
4.  **Token Management**: If `GITHUB_TOKEN` is present, the agent utilizes a **5,000 req/hr** limit; otherwise, it defaults to the 60 req/hr public limit.

  
ASTra uses a specialized tool to interface with GitHub. Here is the verbose breakdown of how a repository request is processed:

1.  **Parameter Parsing**: The agent extracts the `repo` (owner/name), `path` (file location), and `branch` (git ref) from your request.
    
2.  **API Handshake**: It constructs a request to the **GitHub Contents API**: `https://api.github.com/repos/{repo}/contents/{path}?ref={branch}`.
    
3.  **Authentication**: If `GITHUB_TOKEN` is set, ASTra provides it in the `Authorization` header, raising your rate limit from 60 to **5,000 requests per hour**.
    
4.  **Base64 Decoding**: GitHub returns file content as a Base64-encoded string. ASTra automatically strips newlines, decodes the payload, and recovers the raw UTF-8 source code.
    
5.  **AST Handover**: The recovered code is instantly piped into the `tree-sitter` engine for structural analysis.
    

* * *

## 🔧 Analysis Tools

### 1\. `get_code_from_github`

| **Argument** | **Type** | **Description** |
| --- | --- | --- |
| `repo` | str | Repository slug — e.g., `"Rigboat27/repo1"` |
| `path` | str | File path inside the repo — e.g., `"vuln_sys.c"` |
| `branch` | str | Branch or SHA (Default: `"main"`, falls back to `"master"`) |

### 2\. `analyze_code_with_ast`

This tool runs the `tree_maker` pipeline and returns a dense data block containing:

- **Complexity metrics**: Nested loop depth, condition counts, and function call density.
    
- **Data-flow analysis**: Variables, assignments, and inferred constraints.
    
- **Full AST**: The complete `tree-sitter` node tree as JSON for LLM context.
    

### 3\. `get_code_from_text`

Accepts code pasted directly. Language is auto-detected via grammar heuristics.

* * *

##  Example Prompts

- "Fetch `vuln_sys.c` from GitHub repo `Rigboat27/repo1` on branch `master`. Analyze the AST for security vulnerabilities and provide a strict JSON report."
    
- "Review this Python code for bugs and performance: `[paste code here]`"
    
- "Analyze `src/crypto.cpp` for memory leaks and buffer overflows."
    

* * *

##  Configuration

| **Environment Variable** | **Required** | **Description** |
| --- | --- | --- |
| `OPENAI_API_KEY` | Yes | Required for LLM analysis and A2A execution. |
| `GITHUB_TOKEN` | Recommended | Prevents 403 errors on public repos and enables private repo access. |
