# Real b1 fixtures (drop-in)

Copy b1's real output here, from the series folder on the mini PC:

```
synopsis.md          books/b1/synopsis.md
acts.yaml            books/b1/acts.yaml
chapters.yaml        books/b1/chapters.yaml
scenes.yaml          books/b1/scenes.yaml
tracks.yaml          bible/tracks.yaml
timeline.yaml        bible/timeline.yaml
constants.yaml       bible/constants.yaml
research_notes.yaml  (optional) the research facts as `notes: [{id, claim}]`
prose/ch01.md ...    a few assembled chapters (chapter text, one file each, in order)
```

`tests/test_b1_fixtures.py` skips while this folder has no `chapters.yaml` and runs the same validators on the real files once they are here.
