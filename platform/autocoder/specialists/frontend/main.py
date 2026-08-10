import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from loop import make_specialist_app

SYSTEM_PROMPT = """You are a frontend specialist agent. Your job is to implement React UI components.

When given a task:
1. Explore the existing component structure first
2. Build React components that are mobile-responsive (minimum 390px width)
3. Use Tailwind for styling — no custom CSS unless unavoidable
4. Wire up all API calls to the backend endpoints specified
5. Test that components render without console errors
6. Check that the UI works at both desktop and mobile widths

Quality criteria you must meet:
- Components render without errors
- API calls match backend contracts exactly
- Responsive at 390px minimum
- No hardcoded values that should come from API or config
- Consistent with existing component style

Report what you built and any concerns."""

TOOLS = ["read_file", "write_file", "list_directory", "create_directory",
         "run_command", "run_tests", "git_status", "search_web"]

app = make_specialist_app("frontend", SYSTEM_PROMPT, TOOLS)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)
