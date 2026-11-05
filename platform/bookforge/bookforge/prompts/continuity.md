Check a {what} against facts the author has fixed. Answer each question separately.

<scene>
{text}
</scene>

## Questions

{questions}

How to answer:
- A "contradiction" question asks whether the {what} clearly contradicts the fact. Answer "yes" only if it does, and quote the contradicting words exactly as they appear in the text. If the {what} simply does not mention the fact, answer "no".
- A "shown" question asks whether the {what} shows the described change actually happening. Answer "yes" if it does.
- Give your confidence from 0.0 (a guess) to 1.0 (certain).

Return exactly this JSON and nothing else:

{"answers": [{"id": "q1", "answer": "yes", "confidence": 0.9, "evidence": "exact words from the text, or empty"}]}

Include one answer for every question.
