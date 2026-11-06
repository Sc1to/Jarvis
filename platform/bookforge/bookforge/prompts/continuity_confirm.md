A reader flagged a possible contradiction between a fixed fact and a passage of a {what}. Decide whether it is real.

Fixed fact:
{fact}

Passage:
{passage}

Quoted words the flag rests on:
{quote}

Work in this order:
1. "fact_says": the value or claim the fact makes about the matter (an age, a place, a colour, a role).
2. "text_says": what the passage says about the same matter. If the passage says nothing about it, write "nothing".
3. "conflict": true only if the two cannot both be true. Compare numbers and ranges arithmetically (twenty-eight years lies within "late 20s"; "thirty-one" does not). A passage that repeats, supports or is merely compatible with the fact is not a conflict. A tendency (manner, voice, mood) is not a conflict when one line differs.

Give your confidence from 0.0 (a guess) to 1.0 (certain).

Return exactly this JSON and nothing else:

{"fact_says": "...", "text_says": "...", "conflict": false, "confidence": 0.9}
