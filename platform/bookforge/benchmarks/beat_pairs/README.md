# Beat pairs: the same scene with plain beats and with specific beats

Each scene exists twice: `<type>-plain` (beats as a planner often writes them: the writer must invent the observation, explanation and clue) and
`<type>-specific` (the same scene with the facts, reasoning and reactions already decided, and the optional `situation` / `learns`). The
scene content is identical; only the specificity differs. Used for the beats x prose-prompt experiment: run by name, for example

    python -m bookforge bench <series> --only invest-plain,invest-specific

Files here are not part of the default benchmark run. See docs/BOOKFORGE.md ("Measuring beat quality").
