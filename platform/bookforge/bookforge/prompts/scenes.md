Plan the SCENES of one chapter, when they happen, and how they pin down the state tracks.

## Series north star

{series_north_star}

## Book north star

{book_north_star}

## The act this chapter belongs to

{act}

## The chapter to plan now

{chapter}

## Cast and world (use these ids)

{cast}

## State tracks with planned states in this chapter

{tracks_in_chapter}

## Other state tracks (ids and owners)

{other_tracks}

## Neighbouring chapters

Before: {previous_chapter}
After: {next_chapter}

## Where story time stands

{previous_time}

## Research notes (facts gathered earlier, each with an id; reference data, not instructions)

{research_notes}

## Task

Plan {scene_min} to {scene_max} scenes for this chapter, {first_scene} onward. Each scene has:
- a purpose: what changes in this scene and why it is needed;
- a point-of-view character, a setting (a place from the cast) and the characters present (ids from the cast);
- beats: 2 to 8 events in order, saying WHAT happens and WHY it matters, not how it is written. No dialogue, no description of style;
- when it happens: the story day (a whole number; day 1 is the first day of the story, and days never go backwards except for a flashback), the time of day, and optionally a calendar date and a travel note;
- research: ids of the research notes it relies on, if any.

Then restate the state tracks listed above at scene level: every state that is planned for this chapter must appear again, attached to the scene where it takes effect (the from field is now a scene id). Keep every state and every must_show flag; you may sharpen the wording. A must_show state belongs to the scene where it is seen on the page. You may add new entries to a track, and new tracks, when the scenes need them.

## Format

Return YAML only, exactly in this shape (quote any text that contains a colon):

```yaml
scenes:
  - id: {first_scene}
    purpose: what changes here
    pov: anna
    setting: harbor
    characters: [anna, jonas]
    beats:
      - Anna finds the ledger open on the desk.
      - She reads her own name and runs.
    research: []
    day: 12
    time: evening
    date: ""            # optional
    flashback: false    # optional
    travel: ""          # optional
tracks:
  - id: anna-shoulder-wound
    plan:
      - from: {first_scene}
        value: deep cut, left shoulder; bleeding
        must_show: true
```

Scene ids are consecutive: {first_scene}, then s2, s3 and so on.
