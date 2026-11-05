The author read a passage of a scene and left a comment. Turn the comment into a lasting rule for the book, so the problem is prevented or caught next time.

<passage>
{passage}
</passage>

Author's comment: {comment}

Characters present: {characters}

Choose the rule type that fits:
- banned_phrase: the problem is a specific word or phrase. Give the phrase (plain words; start with "re:" only for a regular expression).
- style_rule: a general matter of style that the writer must follow and the critic can judge.
- hard_constraint: a fact or behaviour that must never be contradicted (checked as a yes/no question on every scene).
- character_voice: how one character speaks or thinks (give the character's id as the target, scope "character").

Choose the scope: "series", "book", "character" (with the character id as target) or "scene" (with the scene id as target; use only if the comment is about this scene alone). Choose the severity: "block" (must be fixed), "warn" (report it) or "note" (just record it).

Write the rule text as one plain sentence an editor could apply, and an example of what to avoid (and, if it helps, what to do instead).

Return exactly this JSON and nothing else:

{"type": "style_rule", "scope": "series", "target": "", "severity": "warn", "text": "the rule in one sentence", "example": "a short example", "phrase": ""}
