Plan the SCENES of one chapter, when they happen, and how they pin down the state tracks. The events of the story are fixed in the ledger; you decide how they are shown.

## Series north star

{series_north_star}

## Book north star

{book_north_star}

## The act this chapter belongs to

{act}

## The chapter to plan now

{chapter}

## The ledger: what has happened, what this chapter shows, what is reserved

{ledger_status}

## The story so far (where things stand at the end of the story so far)

{story_so_far}

## Already true when this book begins (inherited from the books before it; not events of this book, but every plan must agree with it)

{carried}

## Cast and world (use these ids)

{cast}

## State tracks with planned states in this chapter

{tracks_in_chapter}

## Other state tracks (ids and owners)

{other_tracks}

## Where story time stands

{previous_time}

## Research (for accuracy and texture only)

{research_notes}

## Task

Plan the scenes of this chapter, {first_scene} onward: as many as the chapter's events need, from 1 to 4, and no more. A chapter with little to tell gets one or two scenes; never stretch it. Each scene has:
- a purpose: what changes in this scene and why it is needed;
- a point-of-view character, a setting (a place from the cast) and the characters present (ids from the cast);
- `starts_with`: the id of the FIRST event of this chapter that this scene tells. Use ONLY these ids, in this order (the events of this chapter): {starting_events}. The scenes are consecutive stretches of the chapter's events: a scene tells everything from its `starts_with` event up to, but not including, the event the next scene starts with, and the last scene runs to the chapter's last event. The first scene starts with the chapter's first event. A scene that only goes on with what the scene before it told (a second scene for the same event) has no `starts_with`. You do not list the other events: every event of the chapter is thereby shown in exactly one scene. An event listed under CONTINUING FROM THE CHAPTER BEFORE is carried on in the first scene: take it up where the chapter before left it, and never start it again;
- beats: the things that happen, in order, as many as the scene needs (at least one), saying WHAT happens and WHY it matters, not how it is written. No dialogue, no description of style. A scene begins where the story so far stands: never restart a situation that is already underway (the people are already inside, the door is already open, the decision is already made), and never repeat a beat of an earlier chapter;
- `end_state`: where things stand when the scene ends: locations, what people hold, who knows what;
- when it happens: `days_later`, how many days after the scene before it happens (0 = the same day; a whole number, never negative), the time of day, and optionally a calendar date and a travel note. A flashback sets `flashback: true` and gives the absolute story `day` instead;
- research: ids of research notes it relies on, if any. Research notes are reference for accuracy and texture only: never turn one into a beat, an obstacle or a plot device.

Then restate the state tracks listed above at scene level: every state planned for this chapter must appear again, attached to the scene where it takes effect (the from field is now a scene id). Keep every state and every must_show flag; you may sharpen the wording. A must_show state belongs to the scene where it is seen on the page. You may add new entries to a track, and new tracks, when the scenes need them. A state that returns to an earlier value needs a `cause`.

## Format

Return YAML only, exactly in this shape (quote any text that contains a colon):

```yaml
scenes:
  - purpose: what changes here
    pov: anna
    setting: harbor
    characters: [anna, jonas]
    starts_with: e3
    beats:
      - Anna finds the ledger open on the desk.
      - She reads her own name and runs.
    end_state: Anna has the ledger and is on the street; Jonas does not know she has seen it.
    research: []
    days_later: 0
    time: evening
    date: ""            # optional
    flashback: false    # optional
    travel: ""          # optional
tracks:
  - id: anna-shoulder-wound
    plan:
      - from: {first_scene}   # the scene where the state takes effect: {first_scene}, s2, s3 ... in the order you wrote them
        value: deep cut, left shoulder; bleeding
        must_show: true
```

Scene ids are consecutive: {first_scene}, then s2, s3 and so on (the tool numbers the scenes: do not write ids).
