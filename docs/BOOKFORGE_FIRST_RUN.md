# Bookforge: first full run on the mini PC

Every bookforge milestone (14.0 to 14.13) is built and tested with scripted models. Nothing has yet run end to end
against a real model. This plan turns the code into a trusted tool, in stages that each end with a go / no-go
decision, so a problem is found in a 10-minute run rather than an overnight one.

Rules of the plan:

- **Shrink the book first.** A short test book (4 chapters, about 8 scenes of 300 to 600 words) exercises every layer
  in an hour or two instead of days. Only stage 7 uses full size.
- **One change at a time.** Turn quality checks on one by one (stage 4) so a bad result has one possible cause.
- **Fix with prompts and settings before code.** Prompts are first drafts. Most findings should end in an edit to a file
  in `<series>/workbench/prompts/`, `style/` or `config.yaml`, all versioned in Git. Only a real defect needs a code change.
- **Keep what the run produced.** At the end of every stage, `git log` in the series folder is your lab notebook.

Time per stage depends on your models and I have no measurements, so none are promised. Stage 4 measures them.

---

## Stage 0. Deploy and preflight (about an hour)

Goal: the service, the models and the tools are all reachable, and the box can run the test suite.

**Two things to settle before deploying** (found while writing this plan; neither is resolved in the repository):

1. **Where the code is.** Milestones 14.8 to 14.13 (staleness, report, assembly, benchmarks, API, dashboard, export,
   workbench) exist only on the branch `claude/confident-carson-2j29yo`, six commits ahead of `main`. `scripts/deploy.sh`
   runs `git pull origin main`, so it would deploy none of them. Merge the branch to `main` first (your decision), or on the
   box check the branch out in the checkout the service runs from (below).
2. **Which checkout the service runs from.** The unit file in the repo (`systemd/platform-bookforge.service`) runs from
   `/home/jarvis/Jarvis/platform/bookforge`, while `deploy.sh` updates `/opt/platform/platform/bookforge`, and the older
   install notes say `/opt/platform/bookforge`. On the box, find the real one and use it as `$BF` for the rest of this plan:

```bash
ssh jarvis@ms-s1
systemctl cat platform-bookforge | grep -E "WorkingDirectory|ExecStart"
BF=/home/jarvis/Jarvis/platform/bookforge     # whatever WorkingDirectory says
cd $BF && git rev-parse --show-toplevel && git branch --show-current
```

Get the code onto the box. If the branch is not merged yet:

```bash
cd $(git rev-parse --show-toplevel)
git fetch origin claude/confident-carson-2j29yo && git checkout claude/confident-carson-2j29yo && git pull
git log --oneline -3                      # should show the 14.13 workbench commit
```

If it is merged, `git pull` on `main` (or `./scripts/deploy.sh bookforge` from the dev machine) does this.

Then install, test, build the dashboard and restart:

```bash
cd $BF && source venv/bin/activate
pip install -r requirements.txt           # includes pywebpush (new since 14.11)
python -m pytest -q                       # the suite, on the real machine and Python version
cd ../../ && bash scripts/build-frontends.sh bookforge   # builds the dashboard and refreshes the Caddy block
sudo systemctl restart platform-bookforge
sleep 3; curl -s localhost:8100/health
sudo systemctl reload caddy
```

(`deploy.sh` builds the frontend on the dev machine and copies `dist/` over instead; either works. Its health check waits
five seconds, which is enough for bookforge.)

Config for the models you actually have. The first mini PC run used Ollama (`llama3.3`); colibri is the design.
Start with whichever answers, and write it into `$BF/config.yaml`:

```yaml
models:
  writer:
    base_url: http://127.0.0.1:11434/v1      # or http://127.0.0.1:8040/v1 for colibri
    model: llama3.3:latest                    # exactly as `curl .../v1/models` lists it
  critic:
    base_url: http://127.0.0.1:11434/v1      # or :8041 for colibri
    model: llama3.3:latest
```

Then:

```bash
python -m bookforge doctor
```

**Must pass:** both endpoints, the web check, `git`, `pandoc` (warn is acceptable until stage 6), config, data dir.

### The context window check (do not skip)

Briefings are up to 16,000 tokens (`briefing.max_tokens`). **Ollama truncates a prompt to its context length without
telling the client**, and its default is small. A truncated briefing silently loses the end of the prompt, which is where
the task and the beats are. Check before anything else:

```bash
# 1. which context length is the server using? (look for num_ctx or "context" in the model info and the server log)
ollama show llama3.3 | head -30
journalctl -u ollama -n 50 --no-pager | grep -i ctx

# 2. prove it: a ~12,000-token prompt whose answer is at the very end
python3 - <<'EOF'
import json, urllib.request
filler = "The harbour was quiet that night. " * 1500
body = {"model": "llama3.3:latest", "messages": [{"role": "user", "content": filler + "\nThe secret word is ZEBRA-42. What is the secret word? Answer with the word only."}]}
req = urllib.request.Request("http://127.0.0.1:11434/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
print(json.load(urllib.request.urlopen(req, timeout=600))["choices"][0]["message"]["content"])
EOF
```

If the answer is not `ZEBRA-42`, the context is too small. Raise it (the setting depends on the Ollama version: the
`OLLAMA_CONTEXT_LENGTH` environment variable, or a derived model with `PARAMETER num_ctx 16384` in a Modelfile), restart
Ollama, and repeat the check. For colibri, do the same test against port 8040 and 8041 and check the model's maximum
context in `c/coli status`. Do not go on until this passes at 16,000 tokens, or lower `briefing.max_tokens` to what passes.

### Memory with both models

If both colibri servers cannot be resident at once, start only the writer and let the critic stages wait: the planner
layers use the critic role. `manage_service` (starting and stopping the critic around its stages) is **not wired up yet**.
Either run both, or point `models.critic` at the same endpoint as the writer for the test book (as in the config above).

### Dashboard and notifications

Open `https://<tailscale-name>/bookforge/` on your phone and laptop. The series list loads. In the header, tap
"Notify me", allow notifications, then check it works:

```bash
curl -s -X POST localhost:8100/api/push/test      # {"data": {"delivered": 1}} and a notification on the phone
```

(iPhones need the page added to the home screen first.)

**Go / no-go:** the branch is on the box, tests pass there, doctor is green, the context check passes, the dashboard loads from the phone.

---

## Stage 1. Direction on a short premise (30 to 60 minutes)

Write a premise of two or three paragraphs in `premise.md` (who, where, what goes wrong, the ending you want). Then make
the series, and set the test-book size in the series' own config:

```bash
S=/opt/platform/data/bookforge/test-series
python -m bookforge new $S --premise premise.md
cat >> $S/config.yaml <<'EOF'
book:
  target_words: 12000
layers:
  acts:     {count: [2, 2]}
  chapters: {count: [4, 4]}
  scenes:   {per_chapter: [2, 3]}
  prose:    {drafts: 2, words: [300, 600]}
research:
  scene_questions: 1
export:
  title: "Test Book"
  author: "Your Name"
EOF
python -m bookforge run $S --until synopsis
```

It stops at the **direction checkpoint**. Read, in this order: `north-star.md`, `books/b1/north-star.md`, `books/b1/synopsis.md`,
`research/*.md`.

What to look for:

- Does each north star say what you meant, and does the ending direction match your premise?
- Is the synopsis a story or a summary of themes? Does it invent things that contradict the premise?
- Research: are the facts about your setting, in the right period and place? (The relevance check exists because the first run
  kept modern facts for a 19th-century town.) A question with "No answer found" is fine; a wrong answer is not.

If something is wrong, **edit the file by hand** (your edits are kept and become the approved version) or improve the prompt:
`bookforge/prompts/series_north_star.md`, `book_north_star.md` and `synopsis.md` copied to `$S/workbench/prompts/` (or edit them
in the dashboard: Workbench, Prompts). Delete the file and rerun to regenerate it.

```bash
python -m bookforge approve $S direction
```

**Go / no-go:** you would be happy to write the book from these three documents. If the model repeatedly produces nothing
usable for this layer, stop here: that is a model or prompt problem, not a bookforge problem, and everything later depends on it.

---

## Stage 2. Structure: acts, cast, chapters, scenes (1 to 2 hours)

```bash
python -m bookforge run $S --until scenes
```

Use `-v` for more output (`python -m bookforge -v run $S --until scenes`). The layers cache each model reply in
`books/b1/work/`, so an interrupted run resumes where it stopped. Run the CLI from `$BF` with the venv active.

Check, after it stops at the **structure checkpoint**:

```bash
python -m bookforge status $S
cat $S/books/b1/reports/review-notes.jsonl        # problems the critic found in the plan and could not get fixed
python -m bookforge state-at $S b1.ch03.s1        # what the bible says is true at a scene
```

- `books/b1/acts.yaml`, `chapters.yaml`, `scenes.yaml`, `bible/constants.yaml`, `bible/tracks.yaml`, `bible/timeline.yaml`: skim
  them, or use the dashboard's Progress and Tracks tabs.
- Is the cast what the story needs? Are the **state tracks** useful (a wound, who knows a secret, where an object is), or
  noise? Tracks are what continuity checks against, so too many vague ones create false alarms later.
- Are the beats concrete things that happen, or themes? Beats like "Anna feels conflicted" are a problem: the critic cannot
  check them and the writer cannot show them.
- Does the timeline make sense (days increase, travel takes time)?

Fix by editing the YAML (it is validated when read; a mistake is reported with the file) or the prompts `acts.md`, `cast.md`,
`chapters.md`, `scenes.md`. Then:

```bash
python -m bookforge approve $S structure
```

**Go / no-go:** the plan is a book you could write by following it. A plan that repeatedly fails validation means the model
cannot yet produce the structured replies layers 4 to 6 need: try the other model for those layers
(`layers.chapters.model: critic` or `writer`) before blaming the prompts.

---

## Stage 3. Chapter 1 prose with the quality checks off (1 hour)

First look at the raw writer, with no model-based checks to confuse the picture. Add to `$S/config.yaml`:

```yaml
qc:
  judge_drafts: false
  continuity_check: false
  critic_check: false
  extract_observed: false
  max_revision_rounds: 0
```

```bash
python -m bookforge briefing $S b1.ch01.s1            # sizes of each part of what the writer will be given
python -m bookforge briefing $S b1.ch01.s1 --full | less   # read it as the model will
python -m bookforge run $S                            # writes chapter 1, then stops at the VOICE checkpoint
python -m bookforge check $S b1.ch01.s1               # mechanical checks
python -m bookforge review $S b1.ch01.s1
```

Read `books/b1/scenes/ch01/s*/final.md` and both drafts (`draft-1.md`, `draft-2.md`). In the dashboard: the scene's Compare tab.

What to look for, and where the fix lives:

| You see | Cause | Fix |
|---|---|---|
| Wrong length | prompt or model | `layers.prose.words`; the `prose.md` prompt |
| Starts with "Sure!" or ends with a moral | model chatter | already blocked mechanically; add to `prose_system.md` |
| Clichés, the same phrases twice | model tics | `style/banned.txt` (the morning report suggests phrases later) |
| Wrong voice | no voice guidance | write `style/guide.md` and put 2 or 3 passages you love in `style/samples/` |
| Ignores a beat | input or model | Workbench: Briefing, "Check the beats"; read the diagnosis |
| Repeats the previous scene's ending | context handling | check the context window again (stage 0) |

**Do this now, once:** write `style/guide.md` (a page: person, tense, sentence feel, what to avoid, two example sentences), put
sample passages in `style/samples/`, extend `style/banned.txt`. Delete a scene's `final.md` and `draft-*.md` to have it written
again, and rerun until chapter 1 reads like something you could edit rather than rewrite. Each change to the guide, samples
or banned list marks written scenes stale; that is expected here (`python -m bookforge stale $S --fix`, or just delete and rewrite).

```bash
python -m bookforge approve $S voice
python -m bookforge run $S                            # the rest of the test book
python -m bookforge report $S
```

**Go / no-go:** the writer, given a good briefing, produces prose in your voice at about the right length without a human
re-prompting it. If not, nothing downstream can rescue it: tune the prompt with the A/B tool on the benchmark scenes
(stage 6) or try another writer model.

---

## Stage 4. Turn the quality checks on, one at a time (2 to 3 hours)

Use a chapter you have already written, and rewrite one scene per step so you can compare:

```bash
python -m bookforge review $S b1.ch01.s1    # the review record, after each step
```

For each step, edit `qc:` in `$S/config.yaml`, delete one scene's `final.md` and `draft-*.md` (and `review.json`), rerun, and read
`review`. Do them in this order, because each is more expensive than the one before:

1. `judge_drafts: true`. Does the chosen draft look better to you than the other? (Workbench: the scene's Compare tab.)
2. `continuity_check: true`. Read the flags and the "unsure" list. **False alarms** (a flag on something that is not a
   contradiction) and **misses** (something wrong that was not flagged) both matter. This check uses the planner model as a
   stand-in for the "System One" endpoint, whose real request format could not be verified. If you can find out whether
   colibri has such an endpoint, only `bookforge/qc/decide.py` needs to change.
3. `critic_check: true` and `max_revision_rounds: 2`. Does the critic quote real weak lines? Does the passage revision fix them
   without damaging the rest? Compare `final.md` with `draft-N.md`.
4. `extract_observed: true`. Are the extracted states right? A gap should be a real difference between plan and prose. Gaps
   become **change requests** (Inbox tab, or `python -m bookforge changes $S`).

**Measure the cost** (this is the information the overnight plan needs):

```bash
jq -s 'map(select(.kind=="llm")) | {calls: length, failed: (map(select(.ok|not))|length),
  seconds: (map(.duration_seconds)|add), prompt_tokens: (map(.usage.prompt_tokens // 0)|add),
  completion_tokens: (map(.usage.completion_tokens // 0)|add)}' $S/books/b1/logs/calls.jsonl
```

Do it before and after one scene to get the per-scene cost. A scene can take 15 to 25 model calls with everything on. Multiply by
your real scene count (about 80 for a 90,000-word book) and decide which checks stay on overnight (`judge_drafts` and
`critic_check` are the expensive ones).

**Calibrate the critic** (the spec's checkpoint 2): in Workbench, Calibration, score about five chapter-1 scenes yourself on
the six criteria. If the critic's ranking disagrees with yours on more than one pair, copy `prompts/critic_rubric.md` to
`workbench/prompts/` and reword it, then re-run the critic. If it scores everything 4, the rubric is too vague.

**Go / no-go:** with the checks you will keep on, a flagged scene is usually one you agree needs work, and an accepted scene is
usually fine. If the checks mostly produce noise, switch the noisy one off (it is a one-line setting) rather than trusting it.

---

## Stage 5. Finish the test book, then break it on purpose (2 hours)

```bash
python -m bookforge run $S
python -m bookforge status $S
```

Scenes marked flagged are expected. Look at each in the dashboard (Progress tab: they open on their own), decide whether to
edit the text (put your own `final.md` in place; it is checked and kept, never rewritten), or let the next run rewrite it.

Then the **change drill**, which tests the part of bookforge that no other tool has:

1. Edit a cast fact: in `bible/constants.yaml` change one fact of a main character (for example the colour of their eyes).
2. `python -m bookforge stale $S`: it should list exactly the scenes that character is in, with the reason.
3. `python -m bookforge stale $S --fix`: scenes that still agree are re-checked in seconds of model time; scenes that contradict the
   change are patched in the passage only. Read one patched scene and the diff (`git log -p -1`).
4. Edit a scene's beats in `scenes.yaml`: that scene (and only it) should come back as "start with redraft".

**Assemble and export:**

```bash
python -m bookforge assemble $S               # refuses if anything is flagged, stale or out of date, and says what
python -m bookforge approve $S final          # after you have read the manuscript
python -m bookforge export $S -f docx -f epub -f companion
```

Open the `.docx` in Word or LibreOffice (Times 12, double spaced, scene breaks centred?) and the `.epub` in a reader app.
**PDF is untested**: install one engine first (`sudo apt install -y texlive-xetex`, or the Typst binary), then
`python -m bookforge export $S -f pdf` and look at the pages (trim size 6 x 9, indents, headings, scene breaks). If the layout
is wrong, the Typst arguments are in `bookforge/export.py` (`_typst_header`, `_pdf_args`) and are the likely place to fix.

**Go / no-go:** the change drill behaves as described, the manuscript reads end to end, and the exports open.

---

## Stage 6. Benchmarks and prompt tuning (1 hour)

```bash
python -m bookforge bench $S --accept      # the first run has no baseline: accept it to start one
```

Then change one thing you suspect (a sentence in `prose.md`, a line in the style guide), and in the dashboard
(Workbench, Prompts) run **A/B test this text**. Vote blind on every pair before the judge's totals appear, then compare. The
point is to find out whether the judge and you agree; if they never do, trust your own reading and use the judge only for
mechanical tie-breaks.

Also try the **rules panel** on something real: take a phrase you keep deleting, make it a banned-phrase rule, use "Test on
chapter 1" before saving, and check its hit count after the next scene. Use "Turn a comment into a rule" on a passage you
dislike and see whether the proposed rule is one you would have written.

**Go / no-go:** you can change a prompt and know, from numbers and your own vote, whether it helped.

---

## Stage 7. The overnight run at full size

Only now reset the series to book size: remove the small-book overrides from `config.yaml` (the `layers:` and `book:` blocks,
the `research.scene_questions` line, and the `qc:` switches you decided to keep off) or start a fresh series from the same
premise and style files:

```bash
python -m bookforge new /opt/platform/data/bookforge/book-one --premise premise.md
cp -r $S/style /opt/platform/data/bookforge/book-one/      # your voice work carries over
cp -r $S/workbench /opt/platform/data/bookforge/book-one/  # rules, prompt overrides, benchmarks, calibration
```

Run the direction and structure stages by hand again (they are human checkpoints and the book is new), approve the voice
checkpoint on its chapter 1, then in the evening start the long run from the dashboard (Overview, Run) or:

```bash
nohup python -m bookforge run /opt/platform/data/bookforge/book-one > run.log 2>&1 &
```

Prefer the dashboard: the job survives you closing the page, and you get a notification on the phone when a checkpoint is
reached, a layer needs you, or the run fails. (A restart of `platform-bookforge` ends a dashboard run; the CLI run above does
not depend on the service. Finished scenes are never lost: start again and it resumes.)

**Next morning:**

1. The notification, then the **morning report** (Inbox tab, or `reports/<date>.md`): needs you, unsure, suggestions for the
   banned list, facts to verify, three revision samples.
2. Read the flagged scenes only. The principle is to read 5 scenes, not 80.
3. Decide the pending change requests (Inbox) and run `stale --fix`.
4. Add the suggested phrases to `style/banned.txt`, run again.

**Stop the run and investigate if:** more than a fifth of the scenes are flagged, the same flag repeats across scenes (a
prompt or rule problem, not a scene problem), `failed` model calls are more than a few percent (`calls.jsonl`), or the
morning report's revision samples show passages getting worse.

---

## What to send back to Claude

After any stage that did not go well, this is enough to diagnose it without the whole book:

```bash
cd $S
git log --oneline | head -30
python -m bookforge status . --json > /tmp/status.json
python -m bookforge review . b1.ch01.s1            # and any scene that went wrong
tail -n 40 books/b1/logs/calls.jsonl | jq -c '{role, model, ok, error, duration_seconds, finish_reason}'
```

Plus the one `calls.jsonl` record of the failing step (it holds the full prompt and the full reply: copy that line, with the
`jq` of its `messages` and `response`). The prompt and the reply together almost always show whether the fault is the
briefing, the template, or the model.

---

## Known open points to watch for

- **Prompts are first drafts.** Every one (`bookforge/prompts/*.md`) will need editing after you read real output. That is
  expected, not a defect.
- **System One is a stand-in.** The continuity confidence is the model's own report, so thresholds (`continuity_flag_threshold`
  0.3) may need tuning against what you see in stage 4.
- **`manage_service` is not wired.** The critic is not started and stopped per stage; memory pressure with both models is yours
  to manage (stage 0).
- **PDF export is untested** against a real engine (stage 5).
- **Character arc lanes** (workbench) are not built.
- **Deploy paths disagree** (stage 0): the unit file, `deploy.sh` and the install notes name three different directories.
- **Python 3.14** is what the mini PC has; the project rule says 3.12. The suite passed there on the first run, but note any
  library that complains.
- **Search engines block the web tool**, so research reads Wikipedia's API. Coverage is good for history, customs, medicine and
  places and thin for niche topics. Research is best-effort; an unanswered question is reported, not fatal.
- **Ollama's habit of answering as if it were the previous request** is handled by a unique first line on every request
  (`isolate_requests`). For colibri, where a prefix cache is wanted, set it off per endpoint if prompts are slow to start.
