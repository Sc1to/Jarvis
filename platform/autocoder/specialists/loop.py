"""
Shared agentic loop for all specialist agents.
Each specialist configures tools and system prompt; this module handles the rest.
"""

import asyncio
import json
import logging
import os
import sys
import time
import uuid

import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from health import health_payload

logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL_SPECIALIST = os.environ.get("MODEL_SPECIALIST", "qwen2.5-coder:32b")
MAX_ITERATIONS = 20

# ── Ollama tool schemas exposed to the LLM ───────────────────────────────────

_ALL_TOOL_SCHEMAS = {
    "read_file": {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file within the project",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Relative path from project root"},
            }, "required": ["path"]},
        },
    },
    "write_file": {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or overwrite a file within the project",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            }, "required": ["path", "content"]},
        },
    },
    "list_directory": {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and folders at a directory path",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Relative path, or '.' for project root"},
            }, "required": ["path"]},
        },
    },
    "create_directory": {
        "type": "function",
        "function": {
            "name": "create_directory",
            "description": "Create a directory (including parents)",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string"},
            }, "required": ["path"]},
        },
    },
    "run_command": {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell command in the project directory",
            "parameters": {"type": "object", "properties": {
                "command": {"type": "string"},
            }, "required": ["command"]},
        },
    },
    "run_tests": {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run the project test suite and return structured results",
            "parameters": {"type": "object", "properties": {
                "test_command": {"type": "string", "description": "Optional specific test command"},
            }},
        },
    },
    "run_python": {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": "Execute a Python code snippet and return output",
            "parameters": {"type": "object", "properties": {
                "code": {"type": "string"},
            }, "required": ["code"]},
        },
    },
    "git_status": {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Get git working tree status",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "git_diff": {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Show current uncommitted diff",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "search_web": {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web for documentation or references",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"},
            }, "required": ["query"]},
        },
    },
}


def build_tool_list(tool_names: list[str]) -> list[dict]:
    return [_ALL_TOOL_SCHEMAS[t] for t in tool_names if t in _ALL_TOOL_SCHEMAS]


# ── Tool dispatch ─────────────────────────────────────────────────────────────

def _dispatch_tool(name: str, args: dict, project_path: str, tracking: dict) -> str:
    try:
        match name:
            case "read_file":
                from tools.filesystem import FilesystemTool
                r = FilesystemTool(project_path).execute({"op": "read_file", "path": args["path"]})
                return r.output if r.success else f"Error: {r.error}"

            case "write_file":
                from tools.filesystem import FilesystemTool
                path = args["path"]
                r = FilesystemTool(project_path).execute({"op": "write_file", "path": path, "content": args["content"]})
                if r.success:
                    # Track file operations
                    abs_path = os.path.join(project_path, path)
                    if os.path.exists(abs_path):
                        tracking.setdefault("files_modified", [])
                        if path not in tracking["files_modified"]:
                            tracking["files_modified"].append(path)
                    else:
                        tracking.setdefault("files_created", [])
                        if path not in tracking["files_created"]:
                            tracking["files_created"].append(path)
                return r.output if r.success else f"Error: {r.error}"

            case "list_directory":
                from tools.filesystem import FilesystemTool
                r = FilesystemTool(project_path).execute({"op": "list_directory", "path": args.get("path", ".")})
                return r.output if r.success else f"Error: {r.error}"

            case "create_directory":
                from tools.filesystem import FilesystemTool
                r = FilesystemTool(project_path).execute({"op": "create_directory", "path": args["path"]})
                return r.output if r.success else f"Error: {r.error}"

            case "run_command":
                from tools.terminal import TerminalTool
                r = TerminalTool(project_path).execute({"op": "execute_command", "command": args["command"], "working_directory": project_path})
                return r.output if r.success else f"Error (exit {r.metadata.get('exit_code', '?')}): {r.error or r.output}"

            case "run_tests":
                from tools.test_runner import TestRunnerTool
                r = TestRunnerTool(project_path).execute({
                    "op": "run_tests",
                    "project_path": project_path,
                    "test_command": args.get("test_command"),
                })
                if r.success:
                    data = json.loads(r.output) if r.output.startswith("{") else {}
                    tracking["tests_passed"] = data.get("failed", 1) == 0
                    tracking["test_summary"] = data
                return r.output if r.success else f"Error: {r.error}"

            case "run_python":
                from tools.code_interpreter import CodeInterpreterTool
                r = CodeInterpreterTool(project_path).execute({"op": "run_python", "code": args["code"], "working_directory": project_path})
                return r.output if r.success else f"Error: {r.error}"

            case "git_status":
                from tools.git_tool import GitTool
                r = GitTool().execute({"op": "status", "repo_path": project_path})
                return r.output if r.success else f"Error: {r.error}"

            case "git_diff":
                from tools.git_tool import GitTool
                r = GitTool().execute({"op": "diff", "repo_path": project_path})
                return r.output if r.success else f"Error: {r.error}"

            case "search_web":
                from tools.web_tool import WebTool
                r = WebTool().execute({"op": "search", "query": args["query"], "session_id": "", "agent_name": "specialist"})
                return r.output if r.success else f"Search unavailable: {r.error}"

            case _:
                return f"Unknown tool: {name}"

    except ImportError:
        return f"Tool '{name}' not available in this environment"
    except Exception as e:
        return f"Tool error: {e}"


# ── Agentic loop ──────────────────────────────────────────────────────────────

async def run_agent_task(
    task_id: str,
    session_id: str,
    project_path: str,
    instructions: str,
    context: dict,
    tool_names: list[str],
    system_prompt: str,
    model: str,
    task_store: dict,
):
    tracking: dict = {"files_created": [], "files_modified": [], "tests_passed": None, "test_summary": {}}
    tools = build_tool_list(tool_names)

    messages = [{"role": "user", "content": instructions}]
    if context:
        messages[0]["content"] = f"Context:\n{json.dumps(context)}\n\n{instructions}"

    start = time.time()
    iteration = 0

    try:
        while iteration < MAX_ITERATIONS:
            iteration += 1
            payload: dict = {
                "model": model,
                "messages": messages,
                "stream": False,
            }
            if tools:
                payload["tools"] = tools

            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
                data = resp.json()

            msg = data.get("message", {})
            tool_calls = msg.get("tool_calls", [])

            if not tool_calls:
                # Final response
                final_text = msg.get("content", "")
                # Try to extract a structured summary from the final response
                concerns: list[str] = []
                notes = final_text[:500] if final_text else "Task completed"

                task_store[task_id] = {
                    "status": "complete",
                    "output": {
                        "files_created": tracking["files_created"],
                        "files_modified": tracking["files_modified"],
                        "tests_passed": tracking.get("tests_passed"),
                        "test_summary": tracking.get("test_summary", {}),
                        "implementation_notes": notes,
                        "concerns": concerns,
                        "duration_seconds": round(time.time() - start, 1),
                    },
                }
                return

            # Execute tool calls
            messages.append({"role": "assistant", "content": msg.get("content", ""), "tool_calls": tool_calls})

            for tc in tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                tool_args = fn.get("arguments", {})
                if isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except Exception:
                        tool_args = {}

                logger.info(f"[{task_id}] tool={tool_name} args={tool_args}")
                result = _dispatch_tool(tool_name, tool_args, project_path, tracking)

                messages.append({
                    "role": "tool",
                    "content": result[:8000],  # cap tool output per message
                })

        # Max iterations reached — treat as complete with whatever was done
        task_store[task_id] = {
            "status": "complete",
            "output": {
                "files_created": tracking["files_created"],
                "files_modified": tracking["files_modified"],
                "tests_passed": tracking.get("tests_passed"),
                "test_summary": tracking.get("test_summary", {}),
                "implementation_notes": f"Completed after {iteration} iterations",
                "concerns": ["Reached max iteration limit"],
                "duration_seconds": round(time.time() - start, 1),
            },
        }

    except Exception as e:
        logger.error(f"Agent task {task_id} failed: {e}", exc_info=True)
        task_store[task_id] = {
            "status": "failed",
            "output": {"error": str(e)},
        }


# ── FastAPI app factory ───────────────────────────────────────────────────────

def make_specialist_app(
    specialist_name: str,
    system_prompt: str,
    tool_names: list[str],
    model: str = MODEL_SPECIALIST,
):
    """Build a FastAPI app for a specialist agent."""
    import time as _time
    from contextlib import asynccontextmanager
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware

    _start = _time.time()
    _tasks: dict[str, dict] = {}

    @asynccontextmanager
    async def lifespan(app):
        yield

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")
    def health():
        return health_payload(_start, "1.0.0", agent=specialist_name)

    @app.post("/task")
    async def post_task(body: dict):
        task_id = str(uuid.uuid4())
        _tasks[task_id] = {"status": "running", "output": None}

        asyncio.create_task(run_agent_task(
            task_id=task_id,
            session_id=body.get("session_id", ""),
            project_path=body.get("project_path", "/tmp"),
            instructions=body.get("instructions", ""),
            context=body.get("context", {}),
            tool_names=tool_names,
            system_prompt=system_prompt,
            model=model,
            task_store=_tasks,
        ))

        return {"task_id": task_id, "status": "ok"}

    @app.get("/task/{task_id}/status")
    def get_task_status(task_id: str):
        task = _tasks.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"status": task["status"], "output": task.get("output")}

    return app
