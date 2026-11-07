Review the scene below as a demanding editor. Score it against the rubric.

## Rubric

{rubric}

## The author's own rules for this scene

{rules}

A rule marked MUST that the scene breaks caps the criterion it belongs to at 2 and should appear among the weakest lines. SHOULD and NOTE rules are weighed but do not cap a score.

## What the scene was meant to do

{brief}

## The voice to match

{voice}

<scene>
{text}
</scene>

Score every criterion with a whole number from 1 to 5. Then quote the three weakest lines of the scene, exactly as they appear in the text (at least 6 words each), and for each say which criterion it hurts and what is wrong with it.

Also go through the planned beats one by one, numbered as in the brief: for each say whether it is "shown" (clearly on the page, in order), "thin" (there but barely), "missing" or "out_of_order", with a short note saying what the scene does instead. This is what the beats_covered score rests on, so say plainly if a beat is only slightly different from the plan.

Return exactly this JSON and nothing else:

{"scores": {"stakes": 3, "voice": 3, "show_dont_tell": 3, "pacing": 3, "dialogue": 3, "beats_covered": 3}, "weakest": [{"criterion": "pacing", "quote": "exact words from the scene", "issue": "what is wrong"}], "beats": [{"beat": 1, "verdict": "shown", "note": "what the scene does for this beat"}]}
