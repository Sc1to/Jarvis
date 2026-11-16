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
- takes a continuous run of events, in ledger order, and ends on a turning point that changes what the characters want or can do (the last event of the act; the last act ends on the book's central decision or its resolution);
- `starts_with`: the id of the FIRST event of the act. Use ONLY these ids, in this order (the events of the book): {starting_events}. The acts are consecutive stretches of the ledger: an act tells everything from its `starts_with` event up to, but not including, the event the next act starts with, and the last act runs to the end of the ledger and holds the resolution. The first act starts with the first event, and every act starts with a LATER event than the act before. So every event belongs to exactly one act. You do not list the other events, and you do not give counts, ids or sizing: the tool works those out from the ledger;
- `turning_point` describes in words the event that ends the act, and nothing else.

Respect "What it is not" in both north stars. Do not plan chapters or scenes here and do not add events, sensory detail or plot.

## Format

Return YAML only, exactly in this shape (quote any text that contains a colon):

```yaml
acts:
  - title: short title
    summary: what happens in this act, 2 to 5 sentences, using only its events
    purpose: its job in the shape of the book, one or two sentences
    turning_point: the event that ends the act, in words
    starts_with: <an id from the list above>
```

The tool numbers the acts ({book_id}.act1, {book_id}.act2 and so on): do not write ids.
