Divide the book into ACTS by assigning the story events of its ledger to them. The chapters will be planned inside each act next.

## Series north star

{series_north_star}

## Book north star

{book_north_star}

## Synopsis

{synopsis}

## The story-event ledger (every event is already decided; you assign them, you do not add or change them)

{ledger_events}

## Research notes (reference only: for accuracy and texture, never a source of events)

{research_notes}

## Task

Cut the ledger into acts. The number of acts follows from the shape of the story (usually three or four; fewer for a short book). {constraints}

Each act:
- takes a continuous run of events, in ledger order, and ends on a turning point that changes what the characters want or can do. Name that event in `turning_point_event`; it must be one of the act's own events;
- lists its events in `events`. EVERY event of the ledger belongs to exactly one act. The last act contains the resolution (the events marked ENDING);
- gives `chapter_count`, which follows from the weight of its events (roughly one chapter per two points of weight; a heavy event may take a chapter alone, several light ones can share one) and NOT from a word target. Never stretch an act with too little material to fill chapters, and never cram it;
- gives `sizing_reason`: one line saying why that many chapters.

Respect "What it is not" in both north stars. Do not plan chapters or scenes here and do not add events, sensory detail or plot.

## Format

Return YAML only, exactly in this shape (quote any text that contains a colon):

```yaml
acts:
  - id: {book_id}.act1
    title: short title
    summary: what happens in this act, 2 to 5 sentences, using only its events
    purpose: its job in the shape of the book, one or two sentences
    turning_point: the event that ends the act, in words
    turning_point_event: e4
    events: [e1, e2, e3, e4]
    chapter_count: 4
    sizing_reason: one line
```

Use the ids {book_id}.act1, {book_id}.act2 and so on, in order.
