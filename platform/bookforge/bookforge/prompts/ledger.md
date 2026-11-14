Extract the STORY EVENTS of this book from its synopsis. The ledger you write is the backbone of every later stage: acts, chapters and scenes will be built from these events, and each stage will be checked against them.

## Series north star

{series_north_star}

## Book north star

{book_north_star}

## Synopsis (the only source of events)

{synopsis}

## What is already true when this book begins (carried over from the series; not events of this book)

{carried}

## Task

List every event of the synopsis, in the order it happens, as numbered events e1, e2, e3... Each event is one thing that happens and changes the situation. Rules:

- Use only what the synopsis says. Do not add plot, do not pad, do not invent complications, do not smooth over gaps. If the synopsis is thin, say so in `questions` instead of filling it.
- Every paragraph of the synopsis must yield at least one event, including the last one (the resolution).
- `excerpt`: the exact words of the synopsis this event comes from, copied character for character (a phrase or sentence, no more than 30 words).
- `once_only: true` for an event that can happen only once (a discovery, a death, a departure, a decision). `false` only for something that genuinely recurs.
- `after`: ids of the events that must already have happened (cause and effect). The list order is the order of telling; an event never comes before one in its `after` list unless it is a flashback.
- `weight`: how much story the event carries: 1 minor, 2 ordinary, 3 major (a turning point, a reveal, a climax). The number of chapters will follow from the total.
- `kind`: event, setup (a secret, promise, clue or threat planted for later), reveal or payoff (it resolves a setup: put the setup's id in `pays_off`), or flashback (told out of story order). A setup is something deliberately planted that the story later pays off (a secret, a promise, a clue, a threat): an ordinary event is not a setup. Every setup needs a payoff that resolves exactly what was planted, and a payoff or reveal never comes before its setup. Do not link events that are merely related.
- `ending: true` on the events that make up the resolution of the book.
- `pov`: the character whose view tells it, only if the book uses several viewpoints.
- `carried_in: true` only for something the synopsis treats as already true at the start (see the carried-over state above).
- `source` is always synopsis here.

If the material is too thin for a full novel, or something the story depends on is open, add `questions`: each says what is missing (`why`) and offers two to four possible complications as `options`, for the author to choose from or reject. Do not turn the options into events.

## Format

Return YAML only, in exactly this shape (quote any text that contains a colon):

```yaml
events:
  - id: e1
    text: one line, what happens
    excerpt: exact words from the synopsis
    once_only: true
    after: []
    kind: event
    weight: 2
    pov: ""
    ending: false
    pays_off: ""
    source: synopsis
questions: []
```

For a question:

```yaml
questions:
  - id: q1
    question: what the author must decide
    why: what is missing
    options: [one possible complication, another]
```
