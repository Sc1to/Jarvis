The scenes of a story plan all happen on the same story day, so no time passes in the plan. Say how many days after the scene before it each scene happens.

## The scenes, in story order

{scenes}

## Rules

- `days_later` is a whole number: 0 when the scene follows the one before it on the same day, 1 when it is the next day, and so on. Never negative.
- Judge from what happens: a night's sleep, a journey, a deadline counted in days, "the next morning", a wait. A scene that goes on directly from the one before is 0. Do not put a day between scenes that follow each other in one sequence of events.
- The story must show a real shape in time: some scenes continue the same day, some come days later. Do not give every scene the same value.
- Give a value for EVERY scene listed.

Return exactly this JSON and nothing else:

{"days_later": {"b2.ch01.s1": 0, "b2.ch01.s2": 0, "b2.ch02.s1": 1}}
