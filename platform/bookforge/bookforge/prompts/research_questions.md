Decide what the author needs to look up before the next planning step.

## What this step researches

{layer_focus}

## The document just written

{document}

## Research already done (reference data)

{research_notes}

## How faithful to the real world this story must be

{realism}

## Task

List at most {max_questions} things this story needs to know or decide before the next planning step. For each, choose a stance:

- "ground": the real world must be right (history, medicine, real places and people, how real things work). It will be looked up on the web.
- "extrapolate": a real basis, an imagined application (a laser weapon, a future drive, an alternative technology). The real constraints will be looked up; you propose what the story assumes.
- "bend": the truth is known and the story deliberately changes it for drama. The truth will be looked up; you propose the deviation and why.
- "invent": nothing real to look up (a made-up rule, name or custom). You propose the rule itself.

Ask about things a good web page can answer: how an institution, trade, place, practice or technology worked or looked in the setting, not about one character's job title and not about a relationship that only exists in this story. "How did a customs house in an English port work day to day, and who worked there?" finds pages; "What did a customs clerk do?" or "How do a clerk and a harbour master relate?" mostly does not. Broaden a narrow question to the institution or practice around it. When the story invents something (a magic with a cost, a device, a custom), that is "invent" (or "extrapolate" if it grows from something real), not a "ground" lookup of the invention itself.

Pick the stance the faithfulness statement above implies. The same laser is "extrapolate" in a story where physics must hold and "invent" where plausible-sounding is enough. History, medicine and real people lean towards "ground". Leave out anything the author could settle in passing without it mattering to the story, and anything already covered by the research above.

For each give: the question or decision in plain words; for "ground", "extrapolate" and "bend" a short web search query (3 to 8 words, include the era or place when it matters, in whatever language will find the best sources); the setting the answer must fit (the story's time, place and world in a few words, for example "England, 1880s"; "any time" for timeless facts); a one-line reason for the stance; for "extrapolate", "bend" and "invent" the proposed assumption, deviation or rule in one or two sentences; and whether the topic is sensitive: true for history, medicine, real places and real people, where a mistake would be embarrassing or harmful, otherwise false.

Return exactly this JSON and nothing else:

{"questions": [{"question": "...", "stance": "ground", "query": "...", "setting": "...", "reason": "...", "rule": "", "sensitive": false}]}

If nothing needs researching or deciding, return {"questions": []}.
