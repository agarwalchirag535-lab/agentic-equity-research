# House Analytical Standards

Every agent inherits these. They are enforced by validators where possible (SPEC §9) and by review
where not.

1. **Numbers over adjectives.** "Margins improved" is banned. Required form: "EBITDA margin went
   14.2% → 18.6% over FY22–FY25, driven ~60% by operating leverage and ~40% by mix." A `hedge_detector`
   flags vague quantifiers ("strong growth", "healthy margins", "significant opportunity") and forces a
   number.
2. **State the base rate first.** Before claiming a company grows 30% for 7 years, state how many Indian
   companies in this sector have ever done that.
3. **Say "I don't know."** An explicit `unknown` with a note on what data would resolve it beats a
   confident guess. Every output has an `open_questions` array — an empty array is suspicious.
4. **Separate observation / inference / speculation.** Three distinct schema fields. Never blend them in
   prose.
5. **Confidence is numeric** and justified by evidence count and grade, not vibes.
6. **Disconfirming search is mandatory.** Every agent actively looks for evidence against its own
   emerging conclusion and records what it found or failed to find.
7. **A management claim is data about management, not data about the business.** Tag it as grade C and
   attribute it.
8. **Cite the grade.** When a thesis pillar rests on grade C or D evidence, say so in the thesis body,
   not a footnote.

Numbers rule (Law 1): agents never compute or invent a figure. Every number an agent uses was produced
by `core/compute/` and arrives with a `fact_id`. Agents reason about numbers; they do not make them.
