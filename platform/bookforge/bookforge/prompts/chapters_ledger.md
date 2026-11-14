Plan the CHAPTERS of one act of the book, and the state tracks they create. The act's story events are fixed in the ledger; you decide how they are told.

## Series north star

{series_north_star}

## Book north star

{book_north_star}

## All acts, for orientation

{acts_overview}

## The act to plan now

{act}

## The ledger: what has happened, what you plan now, what is reserved

{ledger_status}

## The story so far (where each earlier chapter left things)

{story_so_far}

## Already true when this book begins (inherited from the books before it; not events of this book, but every plan must agree with it)

{carried}

## Cast and world (use these ids)

{cast}

## State tracks so far (earlier acts)

{tracks_so_far}

## Research (for accuracy and texture only)

{research_notes}

## Task

Plan exactly {chapter_count} chapters, {first_chapter} to {last_chapter}, covering this act's events from its first to its turning point.

Each chapter has:
- a title and a purpose: what the chapter changes, for the plot or for a character;
- `events_covered`: the ledger event ids it tells. Use only events from "ASSIGNED HERE" (or minor complications you derive below). A `once_only` event is told in exactly ONE chapter: never retell an event listed as DONE, and never touch one RESERVED FOR LATER. Together the chapters cover every event assigned here, in ledger order;
- at least one event that has not been told before: every chapter must move the story forward;
- a summary of what happens, 2 to 5 sentences. Say what happens and why, not how it is told. It must not restate an earlier chapter;
- `end_state`: where things stand when the chapter ends (where the key people are, what they hold, who knows what);
- a point-of-view character and a main setting, using ids from the cast; a tension value from 1 (calm) to 10 (peak), so the act has a shape (rising and falling, not flat).

If the act's events are too few for the number of chapters, give a chapter a minor complication instead of repeating anything: add it to `derived_events`: a small obstacle, delay or consequence that grows out of one event, with `parent` set to that event's id, id `<parent>.1`, `.2`... (at most three per parent), `weight: 1`, `kind: event`, `after: [the parent]`. A derived event is never a new turn of the plot, a reveal, a setup or an ending. Do not add any if the chapters are already full.

Also create or extend STATE TRACKS for everything that changes and will constrain later scenes: injuries, where a key character is, relationships, possessions, who knows which secret. A track belongs to one entity and lists its states over time; each entry says from which chapter the state holds. Set must_show: true when the change itself has to happen on the page. A state that returns to an earlier value needs a `cause`. To extend an existing track repeat its id and give only the new entries. Use plan entries only for chapters of this act.

## Format

Return YAML only, exactly in this shape (quote any text that contains a colon):

```yaml
chapters:
  - id: {first_chapter}
    title: short title
    purpose: what this chapter changes
    summary: what happens
    events_covered: [e1, e2]
    end_state: where things stand at the end
    pov: anna
    setting: harbor
    tension: 4
    research: []        # optional ids of research notes this chapter relies on
derived_events: []      # optional minor complications
tracks:
  - id: anna-shoulder-wound
    entity: anna
    kind: physical      # physical, location, relationship, possession, knowledge, status or other
    plan:
      - from: {first_chapter}
        value: deep cut, left shoulder; bleeding
        must_show: true
```

Chapter ids are consecutive: {first_chapter}, then the next numbers, up to {last_chapter}.
