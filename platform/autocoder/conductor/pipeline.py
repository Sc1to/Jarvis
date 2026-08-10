import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL_ORCHESTRATOR = os.environ.get("MODEL_ORCHESTRATOR", "qwen2.5:72b-instruct-q4_K_M")
PROJECTS_PATH = os.environ.get("PROJECTS_PATH", "/opt/platform/data/projects")

SPECIALIST_URLS = {
    "backend":    "http://localhost:8003",
    "frontend":   "http://localhost:8004",
    "db":         "http://localhost:8005",
    "tester":     "http://localhost:8006",
    "refactorer": "http://localhost:8007",
}

# session_id sets for flow control
_paused: set[str] = set()


def pause_pipeline(session_id: str):
    _paused.add(session_id)


def resume_pipeline(session_id: str):
    _paused.discard(session_id)


# ── LLM helpers ───────────────────────────────────────────────────────────────

async def _llm(prompt: str, system: str = "") -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={"model": MODEL_ORCHESTRATOR, "messages": messages, "stream": False},
            )
            return resp.json().get("message", {}).get("content", "")
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return ""


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


# ── Pipeline steps ────────────────────────────────────────────────────────────

def validate_requirements(requirements: str) -> tuple[bool, str]:
    required = ["objective", "scope", "constraints", "acceptance criteria", "tech context"]
    low = requirements.lower()
    missing = [s for s in required if s not in low]
    if missing:
        return False, f"Missing required sections: {', '.join(missing)}"
    return True, ""


async def plan_pipeline(requirements: str) -> dict:
    prompt = (
        "You are an autocoder orchestrator. Given these requirements, decide which specialist "
        "agents are needed and in what order.\n\n"
        f"Requirements:\n{requirements}\n\n"
        "Available specialists: backend, frontend, db, tester, refactorer\n\n"
        'Return ONLY valid JSON:\n'
        '{"agents": ["agent1", ...], "rationale": "...", "tasks": {"agent1": "specific task", ...}}'
    )
    try:
        response = await _llm(prompt)
        return _parse_json(response)
    except Exception:
        return {
            "agents": ["backend", "tester"],
            "rationale": "Default plan (LLM parse failed)",
            "tasks": {
                "backend": "Implement the backend as specified in requirements",
                "tester": "Write and run tests for the backend implementation",
            },
        }


async def execute_specialist(agent: str, task: str, session_id: str, project_path: str) -> dict:
    url = SPECIALIST_URLS.get(agent)
    if not url:
        return {"success": False, "error": f"Unknown agent: {agent}"}
    try:
        async with httpx.AsyncClient(timeout=1800.0) as client:
            resp = await client.post(f"{url}/task", json={
                "session_id": session_id,
                "project_path": project_path,
                "instructions": task,
                "context": {},
            })
            task_id = resp.json().get("task_id")
            # Poll for completion (max 30 min)
            for _ in range(360):
                await asyncio.sleep(5)
                poll = await client.get(f"{url}/task/{task_id}/status")
                data = poll.json()
                if data.get("status") in ("complete", "failed"):
                    return data
            return {"success": False, "error": "Timeout waiting for agent"}
    except httpx.ConnectError:
        return {"success": False, "error": f"Agent {agent} unreachable at {url}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def review_output(agent: str, output: dict, requirements: str) -> tuple[bool, str]:
    if output.get("error"):
        return False, output["error"]
    prompt = (
        f"You are reviewing the output of the {agent} specialist agent.\n\n"
        f"Requirements:\n{requirements}\n\n"
        f"Agent output:\n{json.dumps(output, indent=2)[:3000]}\n\n"
        f"Does this output adequately fulfill the {agent} stage?\n"
        'Respond with ONLY valid JSON: {"accept": true/false, "reason": "..."}'
    )
    try:
        response = await _llm(prompt)
        result = _parse_json(response)
        return result.get("accept", False), result.get("reason", "")
    except Exception:
        # ponytail: fall back to pass if tests_passed is true
        return bool(output.get("tests_passed")), "Could not parse review response"


def classify_failure(reason: str) -> str:
    low = reason.lower()
    if any(w in low for w in ("unreachable", "unavailable", "timeout", "connect")):
        return "capability"
    if any(w in low for w in ("architect", "design", "structural", "conflict")):
        return "architectural"
    if any(w in low for w in ("scope", "missing", "incomplete", "not specified")):
        return "scope"
    return "solvable"


def git_commit(project_path: str, agent: str, task: str) -> str | None:
    if not os.path.isdir(os.path.join(project_path, ".git")):
        return None
    try:
        subprocess.run(["git", "add", "."], cwd=project_path, check=True, capture_output=True)
        msg = f"autocoder({agent}): {task[:72]}"
        subprocess.run(
            ["git", "commit", "-m", msg, "--author=Platform Conductor <conductor@platform.local>"],
            cwd=project_path, check=True, capture_output=True,
        )
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project_path, capture_output=True, text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


# ── Notification helper ───────────────────────────────────────────────────────

async def _notify(dashboard_url: str, payload: dict):
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{dashboard_url}/internal/event", json=payload)
    except Exception as e:
        logger.warning(f"Dashboard notify failed: {e}")


async def log_event(session_mem, dashboard_url: str, session_id: str,
                    agent: str, event_type: str, content: str = "",
                    metadata: dict | None = None, status: str | None = None,
                    current_task: str | None = None):
    try:
        session_mem.log_event(session_id, agent, event_type, content=content, metadata=metadata or {})
    except Exception as e:
        logger.error(f"session_mem.log_event failed: {e}")
    await _notify(dashboard_url, {
        "session_id": session_id,
        "agent": agent,
        "event_type": event_type,
        "content": content,
        "metadata": metadata or {},
        "timestamp": datetime.utcnow().isoformat(),
        "status": status,
        "current_task": current_task,
    })


# ── Main pipeline coroutine ───────────────────────────────────────────────────

async def start_pipeline(session_id: str, project_id: int | None,
                         requirements: str, session_mem, project_mem,
                         dashboard_url: str):
    project_path = ""
    if project_id:
        project = project_mem.get_project(project_id)
        if project:
            project_path = os.path.join(PROJECTS_PATH, project.name)

    try:
        # Step 1: Validate
        await log_event(session_mem, dashboard_url, session_id, "conductor", "task_start",
                        content="Validating requirements", status="active",
                        current_task="validate_requirements")

        valid, reason = validate_requirements(requirements)
        if not valid:
            await log_event(session_mem, dashboard_url, session_id, "conductor", "failure",
                            content=f"Requirements validation failed: {reason}", status="failed")
            session_mem.close_session(session_id, "failed")
            return

        # Step 2: Plan
        await log_event(session_mem, dashboard_url, session_id, "conductor", "task_start",
                        content="Planning pipeline", status="active", current_task="plan_pipeline")

        plan = await plan_pipeline(requirements)
        await log_event(session_mem, dashboard_url, session_id, "conductor", "task_complete",
                        content=f"Pipeline planned: {plan.get('rationale', '')}",
                        metadata={"plan": plan})

        agents: list[str] = plan.get("agents", [])
        tasks: dict[str, str] = plan.get("tasks", {})
        retry_counts: dict[str, int] = {}
        i = 0

        # Step 3: Execute loop
        while i < len(agents):
            while session_id in _paused:
                await asyncio.sleep(2)

            agent = agents[i]
            task = tasks.get(agent, f"Complete the {agent} stage of the project")

            await log_event(session_mem, dashboard_url, session_id, agent, "task_start",
                            content=f"Starting {agent} stage", status="active",
                            current_task=task[:80])

            output = await execute_specialist(agent, task, session_id, project_path)
            accepted, rev_reason = await review_output(agent, output, requirements)

            if accepted:
                await log_event(session_mem, dashboard_url, session_id, agent, "task_complete",
                                content=f"{agent} stage accepted", status="completed")

                commit_hash = git_commit(project_path, agent, task) if project_path else None
                if commit_hash:
                    await log_event(session_mem, dashboard_url, session_id, "conductor", "commit",
                                    content=f"Committed {agent} stage",
                                    metadata={"hash": commit_hash, "agent": agent})

                retry_counts[agent] = 0
                i += 1

            else:
                failure_type = classify_failure(rev_reason)
                retries = retry_counts.get(agent, 0)

                await log_event(session_mem, dashboard_url, session_id, agent, "failure",
                                content=f"{agent} rejected ({failure_type}): {rev_reason}",
                                metadata={"failure_type": failure_type, "retry": retries},
                                status="failed")

                if failure_type == "architectural":
                    await log_event(session_mem, dashboard_url, session_id, "conductor", "replan",
                                    content="Architectural issue — replanning from scratch")
                    plan = await plan_pipeline(requirements + f"\n\nPrevious attempt failed: {rev_reason}")
                    agents = plan.get("agents", [])
                    tasks = plan.get("tasks", {})
                    retry_counts = {}
                    i = 0

                elif retries >= 2:
                    await log_event(session_mem, dashboard_url, session_id, "conductor", "parked",
                                    content=f"Could not resolve {failure_type} failure in {agent} after {retries + 1} attempts",
                                    status="parked")
                    session_mem.close_session(session_id, "failed")
                    return

                else:
                    if failure_type in ("solvable", "scope"):
                        tasks[agent] = task + f"\n\nPrevious attempt failed: {rev_reason}. Please address this."
                    retry_counts[agent] = retries + 1

        # All stages done
        await log_event(session_mem, dashboard_url, session_id, "conductor", "task_complete",
                        content="Pipeline complete — all stages accepted", status="completed")
        session_mem.close_session(session_id, "success")

    except Exception as e:
        logger.error(f"Pipeline crashed: {e}", exc_info=True)
        try:
            await log_event(session_mem, dashboard_url, session_id, "conductor", "failure",
                            content=f"Pipeline crashed: {e}", status="failed")
            session_mem.close_session(session_id, "failed")
        except Exception:
            pass
