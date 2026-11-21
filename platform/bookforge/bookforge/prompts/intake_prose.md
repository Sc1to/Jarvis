A scene of a novel was written. These capitalised names appear in it but are in nobody's name in the book's cast. Decide for each whether it is a NEW person, place, object or group that the story now has, or only a passing detail.

## The scene

<scene>
{text}
</scene>

## The cast so far (ids and names)

{cast}

## The names to judge

{names}

## Decide, for each name

- "new_entity": a person, place, object or group the story now has and may need again (it acts, is spoken to or about with weight, or is somewhere the plot goes).
- "alias": another name, title or spelling for someone or something already in the cast (give that id in "same_as").
- "detail": a passing mention that needs no cast entry (a street named once, a brand, a distant historical name).
- "not_a_name": a capitalised word that is not a name (a title, a month, the start of a quotation).

For "new_entity" give its kind (character, place, object, group or concept), the exact words of the scene that introduce it ("quote"), and up to two short facts that the scene itself states about it, each copied or closely drawn from the scene's own words.

Return exactly this JSON and nothing else:

{"names": [{"name": "Marek", "verdict": "new_entity", "kind": "character", "same_as": "", "quote": "exact words from the scene", "facts": ["what the scene states"]}]}

Include every name listed.
