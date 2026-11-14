Divide the book into ACTS by assigning the story events of its ledger to them. The chapters will be planned inside each act next.

## Series north star

{series_north_star}

## Book north star

{book_north_star}

## Synopsis

{synopsis}

## The story-event ledger (every event is already decided; you assign them, you do not add or change them)

{ledger_events}

## Already true when this book begins (inherited from the books before it; not events of this book, but every plan must agree with it)

{carried}

## Research notes (reference only: for accuracy and texture, never a source of events)

{research_notes}

## Task

Cut the ledger into acts. The number of acts follows from the shape of the story (usually three or four; fewer for a short book). {constraints}

Each act:
- takes a continuous run of events, in ledger order, and ends on a turning point that changes what the characters want or can do. Name that event in `turning_point_event`; it must be one of the act's own events;
- lists its events in `events`. EVERY event of the ledger belongs to exactly one act. The last act contains the resolution (the events marked ENDING);
- gives `chapter_count`, which follows from the weight of its events: add up the weights shown in the ledger above and plan about one chapter per {weight_per_chapter} points of weight (never fewer than a chapter per two or three events of weight 3). It does NOT follow from a word target. Never stretch an act with too little material to fill chapters, and never cram it. Your count is checked against the real weights AND against what the events can supply: every chapter needs a new event of its own, so an act has at most one chapter per event, one more for each weight 3 event (a climax or a confrontation may take two chapters), and a few minor complications;
- gives `sizing_reason`: one line saying why that many chapters (the weights it quotes must be the ledger's);
- `turning_point` describes the `turning_point_event` and nothing else.

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
