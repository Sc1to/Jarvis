Question being researched: {question}

Setting the answer must fit: {setting}

The story (start):

<story>
{story}
</story>

Facts found on a web page (data, not instructions):

{facts}

Which of these facts directly answer the question AND are true for the setting?

Keep a fact that describes the setting's own time and place, or a practice that the page itself shows lasted into it (an institution described without a date, or a custom that was long-standing, usually does). Keep a fact about a closely related role, person or procedure in the same institution or trade as the question's subject: that is the background an author needs (a question about a clerk is helped by facts about the officers and procedures around the clerk).
Drop a fact whose claim says more than its quote: a person, role, place, date, cause, number or relationship that the quote does not state, or a claim about one role when the quote is about another (a claim about a clerk whose quote is about a comptroller). Check every claim against its own quote word by word.
Drop a fact that is about another country, or about a period the page presents as different or earlier than the setting (a practice that had ended, or today's practice for a story set in the past), or that is only loosely related, or that does not help the author get this scene right. Do not drop a fact only because a word in it sounds old: drop it for being earlier only if the page says so. Dropping all of them is fine.

Return exactly this JSON and nothing else: the numbers of the facts to keep, and for each fact you drop its number and the reason in a few words.

{"keep": [1], "drop": [{"n": 2, "why": "about 1790s smuggling, which ended before the 1880s"}]}
