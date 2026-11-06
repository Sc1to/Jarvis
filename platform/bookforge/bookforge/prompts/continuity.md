Check a {what} against facts the author has fixed. Answer each question separately.

<scene>
{text}
</scene>

## Questions

{questions}

How to answer. Each question is a fact, or a change, tagged `[contradiction]` or `[shown]`. Give a "relation" for every question:

For a `[contradiction]` question, compare the {what} with the fact:
- "contradicts": the {what} states, or clearly implies, the OPPOSITE of the fact (the fact says grey eyes and the {what} says green eyes; the fact says he was born aboard a ship and the {what} says he was born on a planet). Quote the words that conflict, exactly as they appear in the text.
- "agrees": the {what} is consistent with the fact or confirms it. Words that repeat or support the fact are "agrees", never "contradicts".
- "silent": the {what} does not touch the fact. This is the usual answer.
Traits, manner and voice (pragmatic, weary, calm, speaks in short sentences) are tendencies: one line that is longer, livelier or different does not contradict them. A place or a system may be shown in a way the fact does not mention; that is "silent" unless the {what} says the fact is false.

For a `[shown]` question, say whether the {what} shows the described change actually happening:
- "shown": it does (quote the words that show it, if you can).
- "not_shown": it does not.

Give your confidence from 0.0 (a guess) to 1.0 (certain).

Return exactly this JSON and nothing else:

{"answers": [{"id": "q1", "relation": "agrees", "confidence": 0.9, "evidence": "the exact words from the text, or empty"}]}

Include one answer for every question.
