A sentence of a story synopsis has no event in the story-event ledger. Decide what it is, so that nothing the story needs is lost and nothing is invented.

## The sentence

{sentence}

## What comes just before and after it in the synopsis

Before: {before}
After: {after}

## The events the ledger has near it (id and what happens)

{events}

## Decide

Answer one question: what is true AFTER this sentence that was not true before it? A change in the story's situation counts: something happens, someone decides, learns, loses or gains something, something is destroyed or made.
- If you can name such a change, the sentence is `change`. Quote the exact words of the sentence that say so in `words`, and state the change in one line in `change`.
- If the sentence only describes, explains, comments or repeats (what a place is like, what something stands for, how a character feels in general, a restatement of an event told elsewhere), nothing is true afterwards that was not true before: it is `commentary`. Leave `change` and `words` empty.

Return exactly this JSON and nothing else:

{"outcome": "change", "change": "one line", "words": "exact words from the sentence", "reason": "one sentence"}
