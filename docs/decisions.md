# Decisions

Short records of the choices that shaped this design, and what would change them.

## 1. Judge the list at seller capacity, not the score in general

**Decision:** the backtest metric is meetings in the top K, where K is what the team can work in a week.

**Why:** a score can be well calibrated across 10,000 accounts and still put the wrong 40 at the top. Sellers only ever see the top of the list.

**Would change if:** the motion moves to fully automated outreach, where volume isn't capped by people. Then precision across a longer list matters more.

## 2. Cap each source, then reward agreement

**Decision:** each signal source contributes at most 40 points; two or more independent sources multiply intent by 1.25.

**Why:** third-party intent feeds are cheap to add and noisy. Without a cap, the account with the most vendor pings wins. Agreement between sources that don't share data (a web visit and a reply, a job change and a call mention) is much harder to fake.

**Would change if:** one source proved predictive on its own in replay, for example first-party product usage. Its cap would go up.

## 3. Fit is a gate

**Decision:** accounts below the fit bar get no seller action, however active they are. They go to marketing nurture.

**Why:** busy-but-wrong accounts are the most expensive kind of false positive, because they look great on the dashboard.

**Would change if:** the fit model is wrong about a segment. The nurture list is where that shows up first, so it gets reviewed, not ignored.

## 4. Capacity lives in the policy

**Decision:** a rep gets at most five new tasks a day; overflow carries to tomorrow in priority order.

**Why:** a task list longer than a day's work gets triaged by the rep instead of the system, usually by recency or by who they already know. That silently replaces the ranking.

## 5. The model writes the note, nothing else

**Decision:** a language model may write the two-sentence seller note from the decided action and its reasons. It never sees raw signals and never changes a score or an action. A failed or off-topic note falls back to a template.

**Why:** the note is where fluency helps and errors are cheap. Scoring and routing are where errors are expensive and need to be explainable line by line.

## Open questions

- Which reasons do sellers act on, and which do they ignore? That needs seller dispositions captured on each task, which this design doesn't have yet.
- Should "champion job change" create an action at the old account, the new one, or both?
