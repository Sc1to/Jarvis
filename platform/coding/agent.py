"""
Agent loop for the coding assistant.
Uses Ollama's native tool-calling API (non-streaming for tool rounds,
emits SSE events for each step).
"""
import json
import logging
from typing import AsyncGenerator

import httpx

log = logging.getLogger(__name__)

OLLAMA = "http://localhost:11434"
MODEL = "qwen2.5-coder:32b"

SYSTEM_PROMPT = (
    "You are a coding assistant. You have access to the user's project files, "
    "terminal, Git, and GitHub.\n"
    "When given a task:\n"
    "1. Understand the existing codebase before making changes\n"
    "2. Make targeted, minimal changes — do not rewrite what works\n"
    "3. Always run tests after making changes if a test suite exists\n"
    "4. Commit working changes with clear commit messages\n"
    "5. Explain what you did and why after completing a task\n"
    "Ask clarifying questions before starting if requirements are ambiguous."
)

TOOL_DEFS = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a file from the project. Returns the file contents.",
        "parameters": {"type": "object",
            "properties": {"path": {"type": "string", "description": "Path relative to project root"}},
            "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Write content to a file in the project (creates parent dirs if needed).",
        "parameters": {"type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string", "description": "Full file content to write"},
            },
            "required": ["path", "content"]},
    }},
    {"type": "function", "function": {
        "name": "list_directory",
        "description": "List files and directories at a path within the project.",
        "parameters": {"type": "object",
            "properties": {"path": {"type": "string", "description": "Directory path relative to root, default '.'"}},
            "required": []},
    }},
    {"type": "function", "function": {
        "name": "run_command",
        "description": "Run a shell command in the project directory (tests, builds, etc). Do not use for git — use the git tools.",
        "parameters": {"type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"]},
    }},
    {"type": "function", "function": {
        "name": "git_status",
        "description": "Show current git status of the project.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "git_add",
        "description": "Stage files for commit.",
        "parameters": {"type": "object",
            "properties": {"paths": {"type": "array", "items": {"type": "string"}, "description": "Paths to stage, default ['.']"}},
            "required": []},
    }},
    {"type": "function", "function": {
        "name": "git_commit",
        "description": "Commit staged files with a descriptive message.",
        "parameters": {"type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"]},
    }},
    {"type": "function", "function": {
        "name": "git_push",
        "description": "Push commits to remote repository.",
        "parameters": {"type": "object",
            "properties": {
                "remote": {"type": "string", "description": "Remote name, default 'origin'"},
                "branch": {"type": "string", "description": "Branch name, default 'main'"},
            },
            "required": []},
    }},
    {"type": "function", "function": {
        "name": "search_web",
        "description": "Search the web for documentation, error messages, or examples.",
        "parameters": {"type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"]},
    }},
]


def _dispatch(name: str, args: dict, project_path: str) -> str:
    try:
        from tools.filesystem import FilesystemTool
        from tools.terminal import TerminalTool
        from tools.git_tool import GitTool
        from tools.web_tool import WebTool

        fs = FilesystemTool(project_path)
        terminal = TerminalTool(project_path, timeout=120)
        git = GitTool()

        match name:
            case "read_file":
                r = fs.read_file(args["path"])
            case "write_file":
                r = fs.write_file(args["path"], args["content"])
            case "list_directory":
                r = fs.list_directory(args.get("path", "."))
            case "run_command":
                r = terminal.execute_command(args["command"], project_path)
            case "git_status":
                r = git.execute({"op": "status", "repo_path": project_path})
            case "git_add":
                r = git.execute({"op": "add", "repo_path": project_path, "paths": args.get("paths", ["."])})
            case "git_commit":
                r = git.execute({"op": "commit", "repo_path": project_path, "message": args["message"]})
            case "git_push":
                remote = args.get("remote", "origin")
                branch = args.get("branch", "main")
                r = terminal.execute_command(f"git push {remote} {branch}", project_path)
            case "search_web":
                r = WebTool().execute({"op": "search", "query": args["query"]})
            case _:
                return f"Unknown tool: {name}"

        return r.output if r.success else f"Error: {r.error}"
    except ImportError:
        return "Tools not available in this environment"
    except Exception as e:
        return f"Tool error: {e}"


async def run_agent(
    message: str,
    history: list,
    project_path: str,
    model: str = MODEL,
) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted strings for each agent step."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    def sse(obj: dict) -> str:
        return f"data: {json.dumps(obj)}\n\n"

    async with httpx.AsyncClient(timeout=180) as client:
        for _ in range(12):
            r = await client.post(f"{OLLAMA}/api/chat", json={
                "model": model,
                "messages": messages,
                "tools": TOOL_DEFS,
                "stream": False,
            })
            if r.status_code != 200:
                yield sse({"type": "error", "error": f"Ollama error {r.status_code}"})
                return

            data = r.json()
            msg = data.get("message", {})
            tool_calls = msg.get("tool_calls") or []

            if tool_calls:
                messages.append(msg)
                for tc in tool_calls:
                    fn = tc["function"]["name"]
                    # args may be a dict or a JSON string depending on the Ollama version
                    raw_args = tc["function"].get("arguments", {})
                    args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args)

                    yield sse({"type": "tool_call", "tool": fn, "args": args})
                    result = _dispatch(fn, args, project_path)
                    # Truncate large results to avoid bloating the context
                    truncated = result[:4000] + "…[truncated]" if len(result) > 4000 else result
                    messages.append({"role": "tool", "content": truncated})
                    yield sse({"type": "tool_result", "tool": fn, "result": truncated})
            else:
                # Final text response — stream it word-by-word from a fresh streaming call
                messages.append(msg)
                async with client.stream("POST", f"{OLLAMA}/api/chat", json={
                    "model": model,
                    "messages": messages,
                    "stream": True,
                }) as resp:
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                            text = chunk.get("message", {}).get("content", "")
                            if text:
                                yield sse({"type": "text", "text": text})
                        except Exception:
                            pass
                yield sse({"type": "done"})
                return

    yield sse({"type": "done"})
