List the key story milestones of this book: the handful of moments a reader would name if asked "where does it happen?". For example a body found, the first suspect appearing, a tragic event, a betrayal, a breakthrough, a riddle solved, the climax.

## Book north star

{book_north_star}

## The chapters, in order

Each chapter says whether it is "planned" (only the plan exists) or "written" (the scene summaries tell what really happens on the page). For a written chapter go by what the summaries say happened; for a planned chapter go by the plan.

{chapters}

## The list you gave last time (keep a milestone, its chapter and its wording if it still holds)

{previous}

Rules:
- Between {min_count} and {max_count} milestones for the whole book. Only turning points, not every plot detail, and no side thread unless it matters to the main story.
- Each milestone belongs to exactly one chapter, named by its id exactly as written above.
- The label is short and plain, at most 8 words, in the form "Body found", "Anna decides to run".
- No two milestones with the same label.

Return exactly this JSON and nothing else:

{"milestones": [{"chapter": "b1.ch02", "label": "Body found"}]}
