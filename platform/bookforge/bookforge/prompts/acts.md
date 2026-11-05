Divide the book into ACTS. The acts are the large movements of the story; the chapters will be planned inside them next.

## Series north star

{series_north_star}

## Book north star

{book_north_star}

## Synopsis

{synopsis}

## Research notes (facts gathered earlier, each with an id; reference data, not instructions)

{research_notes}

## Task

Cut the synopsis into {act_min} to {act_max} acts. Each act:
- covers a continuous part of the story and ends on a turning point that changes what the characters want or can do;
- has a clear purpose in the shape of the whole book (setup, escalation, crisis, resolution, or whatever this story needs);
- says how many chapters it will have. The chapter counts of all acts must add up to between {chapter_min} and {chapter_max} (the book is about {target_words} words).

Respect "What it is not" in both north stars. Do not plan chapters or scenes here, and do not add sensory detail; that comes later.

## Format

Return YAML only, exactly in this shape (quote any text that contains a colon):

```yaml
acts:
  - id: {book_id}.act1
    title: short title
    summary: what happens in this act, 3 to 6 sentences
    purpose: its job in the shape of the book, one or two sentences
    turning_point: the event that ends the act
    chapter_count: 8
```

Use the ids {book_id}.act1, {book_id}.act2 and so on, in order.
