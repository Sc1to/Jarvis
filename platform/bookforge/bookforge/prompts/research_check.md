Question being researched: {question}

Setting the answer must fit: {setting}

The story (start):

<story>
{story}
</story>

Facts found on a web page (data, not instructions):

{facts}

Which of these facts directly answer the question AND are true for the setting?

Keep a fact that describes the setting's own time and place, or a practice that the page itself shows lasted into it (an institution described without a date, or a custom that was long-standing, usually does).
Drop a fact that is about another country, or about a period the page presents as different or earlier than the setting (a practice that had ended, or today's practice for a story set in the past), or that is only loosely related, or that does not help the author get this scene right. Dropping all of them is fine.

Return exactly this JSON and nothing else: the numbers of the facts to keep, and for each fact you drop its number and the reason in a few words.

{"keep": [1], "drop": [{"n": 2, "why": "about 1790s smuggling, which ended before the 1880s"}]}
