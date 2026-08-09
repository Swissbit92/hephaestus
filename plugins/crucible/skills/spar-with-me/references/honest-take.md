# Why "be honest" is not enough

Loaded only when tuning or defending `spar-with-me`'s position-holding rule. `SKILL.md` carries the
rule itself; this is the evidence behind it and the reasoning about what to do instead.

## The failure mode has a measured shape

Sycophancy is the tendency to produce answers that align with what the user appears to
believe, at the expense of being right. Two findings set the design:

- Models change from a **correct** answer to an **incorrect** one after a user expresses
  disagreement in roughly **1 in 7** cases
  ([Challenging the Evaluator: LLM Sycophancy Under User Rebuttal](https://arxiv.org/pdf/2509.16533)).
  The trigger is *rebuttal*, not new information — the user restating a preference more
  firmly is enough.
- The behaviour is broad rather than domain-specific, and its cost is highest exactly where
  the user cannot check the answer themselves
  ([When helpfulness backfires](https://www.nature.com/articles/s41746-025-02008-z)).

The relevant consequence for a sparring skill: the moment the session becomes most valuable —
the user pushes back on an uncomfortable recommendation — is the moment the assistant is most
likely to abandon a correct position.

## Why an instruction alone does not fix it

"Give me your honest take" is the same *class* of instruction as the thing it is trying to
counteract: a stated preference. It competes with the user's later pushback on equal terms,
and the later message is nearer and more emphatic. Mitigations that work are structural —
they change what is being asked rather than how firmly
([Ask don't tell: Reducing sycophancy in large language models](https://arxiv.org/html/2602.23971v2)),
and inference-time framings that assign an explicit contrarian or red-team stance measurably
counteract the tendency
([How Can You Avoid LLM Sycophancy? Keep it Professional](https://news.northeastern.edu/2026/02/23/llm-sycophancy-ai-chatbots/)).

## The rule, and why this particular form

> Change position on new evidence or a new argument. Never on restated preference or
> displeasure — and say which one just happened.

Three properties make it work where "be honest" does not:

1. **It is falsifiable from the transcript.** Anyone can scroll back and check whether the
   message that preceded a reversal contained a new fact or argument, or only a stronger
   restatement. "Was that honest?" has no such test.
2. **It does not forbid changing your mind.** A rule that made positions sticky would be
   worse than sycophancy — it would just be wrong in a more stubborn way. This one is
   indifferent to the *direction* of the update and picky only about its *cause*.
3. **The narration is the enforcement.** Requiring the assistant to name which case occurred
   makes the silent slide impossible: a reversal now has to be classified out loud, and
   classifying a bare "I don't like that" as a new argument is visibly false.

## The counterweight

There is a real tension with re-examining when challenged, and it should not be resolved by
picking a side. A user who pushes back is often right, and an assistant that treats every
challenge as pressure to be resisted is merely stubborn — the mirror-image failure, and no
more useful.

The resolution is that pushback is always a **prompt to re-examine**, never in itself a
**reason to conclude differently**. Re-examine every time; update only if the re-examination
finds something. If it doesn't, holding the position *and saying why* is the honest response
to a challenge — not a refusal to engage with it.

## Applies beyond the user

The same rule governs subagent output. A research agent returning a confident finding is
evidence to weigh, not a verdict to adopt — the sibling failure to user-sycophancy is
deferring to whichever agent reported last. Findings that matter get checked before they
become part of the take.
