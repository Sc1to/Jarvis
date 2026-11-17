Plan the CHAPTERS of one act of the book, and the state tracks they create. The act's story events are fixed in the ledger; you decide how they are told.

## Series north star

{series_north_star}

## Book north star

{book_north_star}

## All acts, for orientation

{acts_overview}

## The act to plan now

{act}

## The ledger: what has happened and what you plan now

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

Plan the chapters this act's events need, {first_chapter} onward, covering this act's events from its first to its turning point.

The number of chapters follows from the events, not the other way round. About one chapter per event; a weight 3 event (a climax, a confrontation) may take a second chapter that continues it; a minor complication derived from an event may be added to the odd chapter that has too little to tell. The acts stage estimated {chapter_count} chapters: that is a guess, not an order. Write as few or as many as the events need, never more than {max_chapters} ({first_chapter} to {last_chapter}). Every chapter needs an event of its own: when the act's events are all told, STOP. Never fill chapters by retelling an event or borrowing one from another act.

Child events: {child_events}

Each chapter has:
- a title and a purpose: what the chapter changes, for the plot or for a character;
- `starts_with`: the id of the FIRST event this chapter tells. Use ONLY these ids, in this order (they are the events of this act): {starting_events}. (Or a minor complication you derive below.) Never an event listed as DONE. You do not list the other events: the chapters are consecutive stretches of this act's events in ledger order, so a chapter tells everything from its `starts_with` event up to, but not including, the event the next chapter starts with, and the last chapter runs to the act's last event. The first chapter starts with the act's first event, and every chapter starts with a LATER event than the chapter before: so every event is told exactly once, none from another act (never retell an event listed as DONE);
- every chapter must move the story forward. A heavy event (weight 3: a climax, a confrontation, a turning point) may take TWO consecutive chapters: the second chapter says `continues: true` and goes on with it (the tool knows which event), then starts with the next event as usual (a chapter that only carries on a heavy event and tells nothing new has no `starts_with`). No lighter event, and no event for a third chapter;
- a summary of what happens, 2 to 5 sentences. Say what happens and why, not how it is told. Describe only this chapter's own events: it must not restate an earlier chapter, and it says nothing about what comes after it, not even as a goal, a plan or a rumour. A chapter ends where its own events end;
- `end_state`: where things stand when the chapter ends (where the key people are, what they hold, who knows what);
- a point-of-view character and a main setting, using ids from the cast; a tension value from 1 (calm) to 10 (peak), so the act has a shape (rising and falling, not flat).

If the act's events (with their second chapters) are still too few for the number of chapters, give a chapter a minor complication instead of repeating anything: add it to `derived_events` (it is told by the chapter that tells its parent, or by a chapter that starts with it): a small obstacle, delay or consequence that grows out of one event, with `parent` set to that event's id, id `<parent>.1`, `.2`... (at most three per parent), `weight: 1`, `kind: event`, `after: [the parent]`. A derived event is never a new turn of the plot, a reveal, a setup or an ending. Do not add any if the chapters are already full.

Also create or extend STATE TRACKS for everything that changes and will constrain later scenes: injuries, where a key character is, relationships, possessions, who knows which secret. A track belongs to one entity. Write each state INSIDE the chapter where it takes effect, under `states` (you never write chapter ids for it). The first time a track appears give its `entity` and `kind`; after that, its `track` id is enough. Set must_show: true when the change itself has to happen on the page. A state that returns to an earlier value needs a `cause`. To extend an existing track use its id.

## Format

Return YAML only, exactly in this shape (quote any text that contains a colon):

```yaml
chapters:
  - id: {first_chapter}
    title: short title
    purpose: what this chapter changes
    summary: what happens
    starts_with: <an id from the list above>   # the first event this chapter tells (the next chapter's starts_with ends it)
    continues: false       # true only when this chapter goes on with the weight 3 event the chapter before ended with
    end_state: where things stand at the end
    pov: anna
    setting: harbor
    tension: 4
    research: []        # optional ids of research notes this chapter relies on
    states:             # what changes in this chapter and must constrain later scenes
      - track: anna-shoulder-wound
        entity: anna    # only the first time the track appears
        kind: physical  # physical, location, relationship, possession, knowledge, status or other
        value: deep cut, left shoulder; bleeding
        must_show: true # the change itself has to happen on the page
derived_events: []      # optional minor complications, each like this :
#  - text: one line, what the small delay or obstacle is
#    parent: e2          # the event it complicates (the tool sets its id, order and weight)
```

Chapter ids are consecutive: {first_chapter}, then the next numbers, up to {last_chapter}.
