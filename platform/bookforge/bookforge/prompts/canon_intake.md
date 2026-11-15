An author answered a question about their story. Their answer may introduce something new: a person, a place, an object or a group that exists in the story, or a rule of how its world works. Find only what the author's own words introduce. You add nothing and invent nothing.

## The question

{question}

## The author's answer

{answer}

## Already in the story's cast (never list these again)

{cast}

## Rules

- `entities`: each new person, place, object or group the answer brings into the story. `name` is copied exactly as the author wrote it. `kind` is one of character, place, object, group, concept. `facts` are short statements about it taken from the answer's own words (at least one, at most six).
- `rules`: a statement in the answer of how the world works or what is true in it (not of what happens next), copied exactly as the author wrote it.
- If the answer only chooses between options or changes wording, return empty lists. Most answers introduce nothing: that is the normal case.

Return exactly this JSON and nothing else:

{"entities": [{"name": "exact name", "kind": "object", "facts": ["a statement from the answer"]}], "rules": ["an exact sentence from the answer"]}
