Read this synopsis as a careful editor before anything is built from it. Find what is wrong IN THE SYNOPSIS ITSELF: places where it contradicts itself, uses something it never established, or states a cause after its effect. You are not judging style or ambition, and you do not fix anything.

## Synopsis

{synopsis}

## The cast so far (characters, places and things already named in the series)

{cast}

## What is already true when this book begins (from the series)

{carried}

## Author notes (the author's decisions on earlier questions: authoritative, they override the synopsis where they conflict; never raise a question these already settle)

{notes}

## Starting points found by simple checks (not conclusions: confirm or ignore each)

{hints}

## What to look for

- `contradiction`: two statements that cannot both be true: A and not-A, one object in two states (broadcast to everyone, and also buried; lost, and also hidden in the ship's logs), someone doing something after the story says it is no longer possible.
- `unestablished_object`: something used, known or possessed that the text never has anyone acquire, learn or build before it is used (a drive of evidence that no one found).
- `condition_order`: a condition or exchange ("only if", "in exchange for", "on the condition", "because") that is stated AFTER the thing it conditions has already happened, so the condition has no force.
- `unknown_name`: a person, place or thing in the synopsis that is not in the cast, or a name that is clearly another name for a cast entry (the cast says Thorne, the synopsis says Halloway for the same role).
- `cast_conflict`: a cast entry that the synopsis contradicts (a cast character who is dead, absent or someone else in this synopsis).
- `motive_gap`: a character complies with, yields to, or turns against another and nothing in the text forces or persuades them.

## Rules

- Every finding quotes the synopsis: `quotes` holds one to three passages copied character for character (each at most 40 words), the ones in conflict. A finding with no exact quote is discarded.
- Report only what you can point to in the words. If the synopsis is coherent, return an empty list: that is the right answer for a good synopsis. Do not raise a question just to have one, and do not raise two findings about the same words.
- `fixes`: two to four concrete ways the author could resolve it, each one sentence they could choose and apply.

## Format

Return JSON only:

{"findings": [{"type": "contradiction", "quotes": ["exact words", "other exact words"], "why": "one sentence saying why these cannot both hold", "fixes": ["one way to resolve it", "another way"]}]}
