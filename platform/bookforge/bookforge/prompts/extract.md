Record what the scene below actually says about the tracked states.

<scene>
{text}
</scene>

## Tracked states (what the plan expects at this scene)

{tracks}

For each track, report what the scene shows or implies about it:
- "observed": a short statement of what the scene says (empty if it says nothing about this track).
- "matches_plan": true if that agrees with the planned state, false if it clearly differs, null if the scene says nothing about it.
- "evidence": the exact words from the scene that show it, or empty.

Return exactly this JSON and nothing else:

{"observations": [{"track": "track-id", "observed": "...", "matches_plan": true, "evidence": "exact words, or empty"}]}

Include one observation for every track.
