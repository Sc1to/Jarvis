Does the scene below break this rule the author has set?

Rule ({severity}): {rule}
{example}

<scene>
{text}
</scene>

Answer "yes" only if the scene clearly breaks the rule, and quote the words that break it exactly as they appear in the scene (at least 4 words). If the rule is not broken, or the scene does not touch it, answer "no".

Return exactly this JSON and nothing else:

{"violates": true, "evidence": "exact words from the scene, or empty"}
