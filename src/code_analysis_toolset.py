import os
import base64
import asyncio
import json
import aiohttp
import aiofiles
from typing import Any, Optional

# tree_maker.py must live in the same directory as this file.
# It provides: analyze_code(code: str) -> str  (JSON string)
# and:         detect_language(code: str) -> str
from tree_maker import analyze_code, detect_language  # type: ignore[import-untyped]


class CodeAnalysisToolset:
    """
    Toolset for the Code Analysis & Review agent.

    Tools
    -----
    get_code_from_github   – fetch a file from a GitHub repo
    get_code_from_file     – read a local file from disk
    get_code_from_text     – accept raw source code pasted directly by the user
    analyze_code_with_ast  – run tree-sitter (via tree_maker) on source code
                             and return a structured payload for the LLM
    """

    def __init__(self) -> None:
        # Optional GitHub PAT — raises the rate limit from 60 to 5 000 req/hr
        self.github_token: Optional[str] = os.getenv("GITHUB_TOKEN")

    # ------------------------------------------------------------------ #
    # Tool 1 – GitHub                                                     #
    # ------------------------------------------------------------------ #

    async def get_code_from_github(
        self,
        repo: str,
        path: str,
        branch: str = "main",
    ) -> str:
        """Fetch the raw content of a file from a public (or private) GitHub repo.

        Args:
            repo:   Owner/repo slug, e.g. "octocat/Hello-World"
            path:   Path to the file inside the repo, e.g. "src/main.py"
            branch: Branch, tag, or commit SHA (default: "main")

        Returns:
            str: Raw source code of the requested file, or an error message.
        """
        url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 404:
                        return (
                            f"Error: File '{path}' not found in '{repo}' "
                            f"on branch '{branch}'."
                        )
                    if resp.status == 403:
                        return (
                            "Error: GitHub rate limit exceeded. "
                            "Set the GITHUB_TOKEN env var to increase the limit."
                        )
                    resp.raise_for_status()
                    data = await resp.json()

            raw_bytes = base64.b64decode(data["content"])
            return raw_bytes.decode("utf-8", errors="replace")

        except aiohttp.ClientError as exc:
            return f"Error fetching from GitHub: {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"Unexpected error: {exc}"

    # ------------------------------------------------------------------ #
    # Tool 2 – Local file                                                 #
    # ------------------------------------------------------------------ #

    async def get_code_from_file(
        self,
        file_path: str,
    ) -> str:
        """Read source code from a file on the local filesystem.

        Args:
            file_path: Absolute or relative path to the source file.

        Returns:
            str: File contents, or an error message.
        """
        try:
            if not os.path.exists(file_path):
                return f"Error: File '{file_path}' does not exist."
            if not os.path.isfile(file_path):
                return f"Error: '{file_path}' is a directory, not a file."

            async with aiofiles.open(
                file_path, mode="r", encoding="utf-8", errors="replace"
            ) as fh:
                return await fh.read()

        except PermissionError:
            return f"Error: Permission denied reading '{file_path}'."
        except Exception as exc:  # noqa: BLE001
            return f"Error reading file: {exc}"

    # ------------------------------------------------------------------ #
    # Tool 3 – Direct text                                                #
    # ------------------------------------------------------------------ #

    async def get_code_from_text(
        self,
        source_code: str,
        language: str = "",
    ) -> str:
        """Accept source code entered directly as text by the user.

        Use this tool when the user pastes code inline in their message.

        Args:
            source_code: The raw source code string.
            language:    Optional hint for the language. If omitted,
                         detect_language() will infer it automatically.

        Returns:
            str: The source code echoed back with a confirmation header.
        """
        if not source_code.strip():
            return "Error: No source code provided."

        detected = language.strip() or detect_language(source_code)
        line_count = len(source_code.splitlines())
        return (
            f"[Code received — language: {detected}, lines: {line_count}]\n\n"
            + source_code
        )

    # ------------------------------------------------------------------ #
    # Tool 4 – Tree-sitter analysis via tree_maker                       #
    # ------------------------------------------------------------------ #

    async def analyze_code_with_ast(
        self,
        source_code: str,
        language: str = None, **kwargs,
    ) -> str:
        """Parse source code with tree-sitter and return a rich analysis payload.

        Internally calls tree_maker.analyze_code() which produces:
          - Detected language
          - IR (loop depth, nested loops, condition count, function calls)
          - Data-flow analysis (variables, assignments, usages, constraints)
          - Critical code segments (function defs, loops, conditionals)
          - Full AST as a JSON tree

        The combined payload is formatted as a prompt-ready block for the LLM
        to base its code review on.

        Args:
            source_code: Raw source code to analyse (Python, C/C++, or Java).

        Returns:
            str: A structured text block containing the analysis JSON and a
                 review-ready prompt preamble.
        """
        if not source_code.strip():
            return "Error: No source code provided for analysis."

        # Run the CPU-bound tree-sitter work off the event loop
        loop = asyncio.get_event_loop()
        try:
            raw_json: str = await loop.run_in_executor(
                None, analyze_code, source_code
            )
        except Exception as exc:  # noqa: BLE001
            return f"Error running tree-sitter analysis: {exc}"

        # Parse so we can pretty-print a human-friendly summary
        try:
            payload: dict = json.loads(raw_json)
        except json.JSONDecodeError:
            # If parsing failed just return the raw string
            return raw_json

        # Guard: unsupported language
        if "error" in payload:
            return (
                f"tree_maker error: {payload['error']}\n"
                "Supported languages: python, cpp, java.\n"
                "Please specify one of these languages."
            )

        ir = payload.get("ir", {})
        df = payload.get("data_flow", {})
        segments = payload.get("critical_code_segments", [])
        language = payload.get("language", "unknown")

# Convert payload to string and check size
        ast_payload_str = json.dumps(payload, indent=2)
        
        # If payload is too large (> 15,000 chars), we truncate the AST part 
        # to keep the LLM within token limits.
        if len(ast_payload_str) > 15000:
             ast_payload_str = json.dumps({k:v for k,v in payload.items() if k != 'ast'}, indent=2)
             ast_payload_str += "\n\n[NOTE: Full AST truncated due to size. Using IR and Critical Segments only.]"



        summary = f"""
[AST ANALYSIS COMPLETE]
LANGUAGE: {language.upper()}
COMPLEXITY: Max Depth {ir.get('max_loop_depth', 0)}, Conditionals {ir.get('conditions', 0)}

AST DATA & SOURCE CODE:
{ast_payload_str}

[SYSTEM OVERRIDE: OUTPUT PROTOCOL]
Based on the AST and source code above, return your final review strictly as a JSON object matching THIS EXACT SCHEMA. You MUST include 'status', 'overview', and 'analysis_summary'.

When writing the 'patched_code', do not use weak sanitization (like string replacement). You MUST implement the most secure, modern standard (e.g., parameterized queries or safe subprocess calls). 

{{
    "status": "success",
    "overview": "Brief, one-sentence purpose of the code.",
    "analysis_summary": {{
        "bugs_found": 0,
        "security_issues": 0,
        "performance_issues": 0
    }},
    "findings": [
        {{
            "category": "Security|Bug|Performance|Quality",
            "severity": "High|Medium|Low",
            "explanation": "Brief, to-the-point examiner-style explanation."
        }}
    ],
    "patched_code": "string (the fully secured and optimized code. NO COMMENTS ALLOWED.)"
}}
"""
        return summary

    # ------------------------------------------------------------------ #
    # Registration                                                        #
    # ------------------------------------------------------------------ #

    def get_tools(self) -> dict[str, Any]:
        """Return the tool registry used by OpenAIAgentExecutor."""
        return {
            "get_code_from_github": self,
            "get_code_from_file": self,
            "get_code_from_text": self,
            "analyze_code_with_ast": self,
        }
