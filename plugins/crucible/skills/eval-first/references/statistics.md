# Pre-flight: can this eval see the difference you care about?

Run these three checks before freezing a baseline or reading an A/B result. Each one has
turned a confident result into noise at least once.

## 1. Determinism — do repeated runs differ at all?

Run **one** case twice with the exact production settings. Then
`reliability.deterministic_runs([out1, out2])`:

- **Identical** (temperature 0, a response cache, a seeded sampler): repeating a case
  measures nothing. In one A/B, 5 repeats per arm returned byte-identical aggregates
  because the extractor ran at temperature 0, so replication had to come from more
  *cases* (58 probes), not more repeats. Keep k = 1 or 2 per case as a determinism
  pre-flight and spend the budget on cases.
- **Different**: the system is stochastic. Use k ≥ 10 per case before concluding anything
  about a rate, and never compare two single runs.

## 2. Resolution — how wide is the error bar on what you have?

`python3 scripts/reliability.py ci --passes <c> --n <n>` prints the Wilson interval. A
small n is wider than intuition says. 7/10 is a 95% interval of [0.40, 0.89]. 10/10 still
only shows "at least about 0.72". Two arms whose intervals overlap heavily have not been
told apart. Report the interval with the rate, not instead of it.

Wilson rather than the textbook ±1.96·√(p(1−p)/n): the normal approximation is too narrow
for small n and collapses to zero width at 0% and 100%, the rates gates produce most.

## 3. Sample size — how many cases would the claimed effect need?

`python3 scripts/reliability.py n --p <baseline rate> --delta <smallest change worth
detecting>` gives cases per arm at 80% power (two-sided, α = 0.05). Detecting +10 points
from a 70% baseline needs about 290 cases per arm, and +20 points needs about 70. If the
eval has fewer cases than that, say so in the result. "No significant difference" from an
underpowered eval is not evidence of parity.

## What to write down

State all three with the result. For example: *"runs are stochastic (pre-flight differed);
candidate 41/50 [0.69, 0.90] vs legacy 37/50 [0.61, 0.84]; the eval can resolve about ±0.18
at this n."* A number with no resolution attached invites a tolerance finer than the
instrument.
