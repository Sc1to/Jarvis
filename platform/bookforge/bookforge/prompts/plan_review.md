Review the proposed {what} as a demanding editor.

## Series north star

{series_north_star}

## Book north star

{book_north_star}

## The parent it must fit

{parent}

## State tracks relevant here (the bible's state of the story)

{tracks}

## The story-event ledger (what has happened, what belongs here, what is reserved for later)

{ledger}

## The proposed {what}

{proposed}

Check that the proposal:
- fits its parent: it covers what the parent says, adds nothing that contradicts it, and leaves nothing out;
- respects both north stars, above all "What it is not";
- agrees with the state tracks (nobody does what an injury forbids, nobody knows what they cannot know yet);
- gives every item a clear purpose;
- agrees with the ledger, when there is one: it tells every event assigned here, retells none that is DONE, and touches none that is RESERVED FOR LATER.

List only real problems, each naming the item it concerns. If there are none, say so.

Return exactly this JSON and nothing else:

{"ok": false, "problems": [{"item": "b1.ch03", "issue": "what is wrong and what it should do instead"}]}

When there are no problems, return {"ok": true, "problems": []}.
