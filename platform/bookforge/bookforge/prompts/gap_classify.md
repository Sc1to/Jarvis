A question about a story came up while its plan was being checked. Decide whether answering it needs a fact about the WORLD or a decision about the STORY.

## The question

{question}

Why it was asked: {why}
Kind of finding: {type}

## The setting of the book (its realism statement)

{realism}

## Decide

- `world_fact`: it can be answered by what is true or plausible in the setting: how a thing works, what existed or was possible then and there, what a technology or institution would do, what a real person or place was like. Someone with the right knowledge (or an invented rule of this world) could answer it without choosing what happens in the story.
- `story_decision`: it can only be answered by choosing what happens, who does what, or why a character acts: how a character comes to have something, why one person yields to another, which of two versions of events is the story's.

If it is a world fact, state the fact to establish in one line (`fact`), phrased as a question a researcher or the author could answer.

Return exactly this JSON and nothing else:

{"kind": "world_fact", "fact": "one line, or empty for a story decision", "reason": "one sentence"}
