Plan the SCENES of one chapter, when they happen, and how they pin down the state tracks. The events of the story are fixed in the ledger; you decide how they are shown.

## Series north star

{series_north_star}

## Book north star

{book_north_star}

## The act this chapter belongs to

{act}

## The chapter to plan now

{chapter}

## The ledger: what has happened and what this chapter shows

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

Plan the scenes of this chapter, {first_scene} onward: as many as the chapter's events need, from 1 to 4, and no more. {length_guidance} Each scene has:
- a purpose: what changes in this scene and why it is needed;
- a point-of-view character, a setting (a place from the cast) and the characters present (ids from the cast);
- `starts_with`: the id of the FIRST event of this chapter that this scene tells. Use ONLY these ids, in this order (the events of this chapter): {starting_events}. The scenes are consecutive stretches of the chapter's events: a scene tells everything from its `starts_with` event up to, but not including, the event the next scene starts with, and the last scene runs to the chapter's last event. The first scene starts with the chapter's first event. A scene that only goes on with what the scene before it told (a second scene for the same event) has no `starts_with`. You do not list the other events: every event of the chapter is thereby shown in exactly one scene. An event listed under CONTINUING FROM THE CHAPTER BEFORE is carried on in the first scene: take it up where the chapter before left it, and never start it again;
- `situation` (optional, one or two sentences): where things stand when the scene opens, including what the viewpoint character knows, suspects or wrongly believes. Leave it out only when the scene simply continues the moment before;
- `learns` (optional, one sentence): what is new by the end: something learned, decided, or changed between people. A quiet scene may only deepen a relationship or show a character; that is a valid answer and needs no conflict or twist;
- beats: the things that happen, in order, as many as the scene needs (at least one). The writer will invent none of the story logic, so the beats must carry it. Each beat is one concrete, observable event, and says WHAT happens and WHY it matters, not how it is written (no dialogue, no description of style). Where it matters, a beat says what is seen or found (the actual object, mark or fact, never "something unusual" or "a clue"), what each person in the scene knows, wants and does about it, what follows from it (a conclusion only as far as the evidence in the story so far supports it; a guess is marked as a guess), and what it changes. Give people reasons and reactions, including ordinary ones: agreement, humour, familiarity and tiredness are as good as disagreement, and a capable person is not made foolish so that another can correct them. A weak beat: "Nora notices something odd about the fridge. They find another clue." A strong one: "Nora opens the fridge in the lodge, closed for three weeks: it is empty except for a carton of milk, opened, with a use-by date that falls after the closure. Dan offers an innocent explanation (the winter maintenance crew), which is reasonable; Nora accepts it as possible, not proof, and asks him to find out who had access last week." The same applies to any kind of story: a romance beat names the look, the sentence left unsaid and the decision it leads to; an adventure beat names the obstacle, the choice and its cost. A scene begins where the story so far stands: never restart a situation that is already underway (the people are already inside, the door is already open, the decision is already made), and never repeat a beat of an earlier chapter;
- `end_state`: where things stand when the scene ends: locations, what people hold, who knows what;
- when it happens: `days_later`, how many days after the scene before it happens (0 = the same day; a whole number, never negative), the time of day, and optionally a calendar date and a travel note. A flashback sets `flashback: true` and gives the absolute story `day` instead;
- research: ids of research notes it relies on, if any. Research notes are reference for accuracy and texture only: never turn one into a beat, an obstacle or a plot device.

The state tracks listed above are already planned for the chapter as a whole. Write a state INSIDE the scene where it takes effect or is seen on the page, under `states` (never write scene ids for it): give the `track` id and the state, you may sharpen the wording, and keep must_show: true for a state that must be seen. A track you do not mention here stays as planned and the tool attaches it to a scene. You may add states for new tracks (give `entity` and `kind` the first time). A state that returns to an earlier value needs no `cause`: the tool writes it.

## Format

Return YAML only, exactly in this shape (quote any text that contains a colon):

```yaml
scenes:
  - purpose: what changes here
    pov: anna
    setting: harbor
    characters: [anna, jonas]
    starts_with: <an id from the list above>
    beats:
      - Anna finds the ledger open on the desk.
      - She reads her own name and runs.
    end_state: Anna has the ledger and is on the street; Jonas does not know she has seen it.
    situation: Anna has come to the harbor to meet Jonas; she does not yet know the ledger exists.   # optional
    learns: Anna learns the ledger holds her own name.   # optional
    states:             # optional: states that change or show in this scene
      - track: anna-shoulder-wound
        value: deep cut, left shoulder; bleeding
        must_show: true
        status: established   # or observed, hypothesis (suspected only), false_belief (wrongly believed); leave out when it is simply true
    research: []
    days_later: <0 if it follows the scene before it on the same day, 1 for the next day, and so on>
    time: evening
    date: ""            # optional
    flashback: false    # optional
    travel: ""          # optional
```

Scene ids are consecutive: {first_scene}, then s2, s3 and so on (the tool numbers the scenes: do not write ids).
