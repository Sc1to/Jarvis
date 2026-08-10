# MAINTENANCE_PROMPT.md
# Reusable end-of-session documentation maintenance routine.
# Run this at the end of every Claude Code session, every time, no exceptions.
# Copy and paste this prompt into Claude Code when wrapping up a session.

---

## WHEN TO RUN THIS

At the end of every build session before closing Claude Code.
Even if you think nothing changed that affects the docs — run it anyway.
Documentation drift is invisible until it becomes a problem.

---

## THE PROMPT

```
Before we close this session, run the documentation maintenance routine.

Read every document in the docs/ directory in full:
- CLAUDE.md
- docs/ARCHITECTURE.md
- docs/STACK.md
- docs/BUILD_SEQUENCE.md
- docs/SETUP.md
- docs/TRADING_ARCHITECTURE.md
- docs/IBKR_SETUP.md
- Any other .md files present in docs/

Then read everything we built or changed in this session.

Perform the following maintenance tasks:

---

TASK 1 — UPDATE BUILD STATUS IN CLAUDE.md

Update the BUILD_STATUS section to reflect exactly what was completed
in this session. Mark completed components with [x]. Update:
- Current phase
- Last completed component
- Currently working on (none — session ending)
- Blocked on (none, or real blockers if they exist)

Do this via surgical edit — only touch the BUILD_STATUS section.
Do not rewrite or reformat any other section of CLAUDE.md.

---

TASK 2 — MERGE NEW INFORMATION INTO EXISTING DOCUMENTS

For each document, check whether anything built in this session:
- Contradicts existing content → resolve the contradiction, keep the
  more accurate/current version, note what changed
- Adds new information not yet documented → add it to the correct
  document in the correct section
- Makes existing content outdated → update it
- Duplicates content already in another document → remove the duplicate,
  keep one authoritative location

Rules for where information lives:
- System design, agent definitions, flows → ARCHITECTURE.md
- Tech stack, versions, ports, install commands → STACK.md
- Build order, Claude Code prompts → BUILD_SEQUENCE.md
- Ubuntu setup, physical machine setup → SETUP.md
- Trading system design → TRADING_ARCHITECTURE.md
- IBKR connection and setup → IBKR_SETUP.md
- Session state, hard rules, naming conventions → CLAUDE.md

If information belongs in multiple documents (e.g. a new port assignment
belongs in both STACK.md port map and ARCHITECTURE.md service list),
add it to both — that is not a duplicate, that is appropriate redundancy.

---

TASK 3 — CHECK FOR CONTRADICTIONS ACROSS DOCUMENTS

Scan for cases where two documents say different things about the same thing:
- Port numbers
- File paths
- Service names
- API endpoints
- Technology choices
- Naming conventions

Resolve every contradiction. The more recently built implementation wins
over the older document. Note every resolution.

---

TASK 4 — VERIFY NAMING CONVENTION COMPLIANCE

Check that all agents, services, and components built in this session
follow the naming convention defined in CLAUDE.md:

{domain}_{role}_{variant}

Examples:
  autocoder_conductor
  autocoder_specialist_backend
  trading_monitor_stocks
  trading_wsb_dd
  platform_chat

If anything was named incorrectly: flag it with the correct name.
Do not rename files automatically — flag for manual correction next session.

---

TASK 5 — UPDATE STACK.MD IF NEW DEPENDENCIES ADDED

If any new Python packages, npm packages, or system dependencies were
introduced in this session:
- Add to the relevant service requirements.txt
- Add to STACK.md with version and purpose
- Add to the port map if a new service was created
- Add to the systemd services registry if a new service was deployed

---

TASK 6 — PRODUCE MAINTENANCE REPORT

After completing all tasks, produce a brief maintenance report:

DOCUMENTATION MAINTENANCE REPORT — {date} {time}

Documents updated:
  CLAUDE.md           — BUILD_STATUS updated, phase X marked complete
  STACK.md            — added {package} to trading service dependencies
  ARCHITECTURE.md     — updated {section} to reflect {change}
  ... etc

Contradictions resolved:
  {description of each resolution}

Naming convention issues flagged:
  {any violations found}

Documents with no changes needed:
  {list}

Next session should start at:
  Phase {X} — {component name}
  Prompt available in BUILD_SEQUENCE.md section {X.Y}

---

Important: Do not rewrite documents wholesale. Make surgical, targeted edits.
The goal is accurate documentation, not reformatted documentation.
If a section is correct and current, leave it exactly as is.
```

---

## NOTES ON RUNNING THIS ROUTINE

**If Claude Code flags a contradiction it cannot resolve:**
It will ask you which version is correct. Answer and let it update accordingly.

**If a document grows very long:**
Do not split it into multiple files without updating all cross-references.
Flag it in the maintenance report and we will decide together.

**If Claude Code finds something undocumented:**
Better to have it ask where it belongs than to silently drop it.
The maintenance report should always note additions.

**Frequency:**
Every session. Non-negotiable. Ten minutes of maintenance now saves hours
of confusion later when the system is more complex.
