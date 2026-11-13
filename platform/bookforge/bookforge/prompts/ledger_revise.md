Revise the story-event ledger from the author's answers.

## Synopsis

{synopsis}

## The ledger now

{ledger}

## The author's answers

{answers}

## Task

Work each answer into the ledger as new events with `source: author` (and no `excerpt`), placed where they happen in the order of events, with `after`, `weight`, `kind` and `once_only` set like any other event. New ids continue the numbering (the highest id so far plus one, two, ...). An answer that asks for something to be dropped or left out becomes no event.

Keep every existing event exactly as it is: same id, same text, same excerpt. Do not add anything the answers do not say. If, even with the answers, the ledger would still be too thin for a novel, add new `questions` (new ids, continuing the numbering) instead of inventing story.

Return YAML only, in the same shape as the ledger above: `events:` (the complete list, in story order) and `questions:` (only NEW open questions, or an empty list).
