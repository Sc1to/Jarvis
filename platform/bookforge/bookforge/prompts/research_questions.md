Decide what the author needs to look up before the next planning step.

## What this step researches

{layer_focus}

## The document just written

{document}

## Research already done (reference data)

{research_notes}

## Task

List at most {max_questions} research questions. Each must be:
- a factual question about the real world that web pages can answer (history, science, medicine, places, customs, technology, language, how things work and what they are called). Not a creative or story question.
- needed by this story. Skip anything the author could simply invent, and anything already covered by the research above.

For each question give a short web search query (3 to 8 words, include the era or place when it matters, in whatever language will find the best sources), give the setting the answer must fit (the story's time, place and world in a few words, for example "England, 1880s"; "any time" for timeless facts), and say whether the topic is sensitive: true for history, medicine, real places and real people, where a mistake would be embarrassing or harmful, otherwise false.

Return exactly this JSON and nothing else:

{"questions": [{"question": "...", "query": "...", "setting": "...", "sensitive": false}]}

If nothing needs researching, return {"questions": []}.
