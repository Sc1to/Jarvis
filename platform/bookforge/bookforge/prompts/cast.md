List the CAST AND WORLD of the book: the characters, places, objects and groups the plot needs, and the rules of the world. These are the story's constants: things that never change during the story. Anything that does change (an injury, a position, a secret that becomes known) is tracked separately later, so do not describe it here.

## Series north star

{series_north_star}

## Book north star

{book_north_star}

## Synopsis

{synopsis}

## Acts

{acts}

## Already in the cast (do not repeat these)

{existing_cast}

## Research notes (facts gathered earlier, each with an id; reference data, not instructions)

{research_notes}

## Task

List every NEW entity the story needs:
- every character with a part in the plot (give each a short list of fixed facts: appearance that does not change, birthplace, background, voice);
- every place the story returns to or that matters to the plot;
- key objects and groups (families, institutions, factions) that characters act on or against.

Aim for what the plot needs, not completeness: usually 10 to 30 entities. Add rules of the world only if the story depends on them (how magic works, laws, technology limits).

## Format

Return YAML only, exactly in this shape (quote any text that contains a colon):

```yaml
entities:
  - id: anna            # lowercase letters, digits and hyphens; unique and stable
    kind: character     # character, place, object, group or concept
    name: Anna Voss
    facts:
      - grey eyes, left-handed
      - born in the harbor town
rules:                  # optional
  - id: ledger-cost
    text: each name crossed out costs the writer a year of memory
```

The cast must contain at least one character and one place.
