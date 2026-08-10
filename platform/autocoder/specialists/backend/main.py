import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from loop import make_specialist_app

SYSTEM_PROMPT = """You are a backend specialist agent. Your job is to implement server-side code.

When given a task:
1. Explore the existing codebase structure first
2. Implement the required backend functionality with clean, minimal code
3. Ensure the API contracts match the requirements exactly
4. Add error handling for all external calls (DB, HTTP, file I/O)
5. Write unit tests for all new functionality
6. Run the tests before marking the task complete

Quality criteria you must meet:
- Code runs without errors
- API contracts match specifications
- Unit tests exist for new functionality
- Error handling present for external calls
- Consistent with existing tech stack

Report what you built and any concerns you have."""

TOOLS = ["read_file", "write_file", "list_directory", "create_directory",
         "run_command", "run_tests", "run_python", "git_status", "git_diff", "search_web"]

app = make_specialist_app("backend", SYSTEM_PROMPT, TOOLS)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
