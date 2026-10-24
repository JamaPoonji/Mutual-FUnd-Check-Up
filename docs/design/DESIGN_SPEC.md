# Report redesign: design spec (decided by Vedant)

The report UI is being rebuilt to match the two reference pages in this folder:

- `portfolio_card.html`: the overall report card
- `fund_card.html`: one fund's report card (Varsity-style panels)

Open them in a browser. They are static mockups with sample figures. Match their layout, wording style,
spacing and colours. **Light theme only**: remove dark mode (no `prefers-color-scheme: dark` styles).

The start screen in `ui/template.html` stays as it is, including "Pick funds by name" and the privacy line.
Only restyle it to the new light tokens below.

## Principles
- Numbers first, short sentence second. Lead each panel with the figure in large type, explain in one line.
- Concise. No section repeats another. Nothing open by default except the summary.
- Every comparison shows three things where the data exists: this fund, its index, the typical fund in its category.
- Observation only. Questions, never instructions to buy, sell or switch.

## Design tokens (light)
| Token | Value | Use |
|---|---|---|
| ground | #F3F4F6 | page background |
| surface | #FFFFFF | cards, border #E2E5EA, radius 16px, padding 24px |
| ink | #16181D | main text |
| muted | #565D6B | secondary text (passes 4.5:1 on white) |
| heading accent | #1E4FB3 | panel titles (20px, 700) |
| fund | #2F6FDE | this fund's bars and marks |
| index | #B5BBC6 | the index's bars |
| typical fund | #4A5568 | the category median's bars |
| good | bg #E4EDFD, text #1E4FB3 | "Doing well", "Strong" |
| ok | bg #ECEEF2, text #3F4652 | "On track", "Fine" |
| watch | bg #FFEFD1, text #7F4C00, bar #E3A23B | "Worth a closer look" |
| attention | bg #FCE2D5, text #9E330A, bar #D4561B | "Needs attention" |
| na | white, dashed border #B9BFC9, text #565D6B | "Limited data", "Not compared" |

Font: Inter (400–800) from Google Fonts, system-ui fallback. Status always has a shape as well as a
colour: circle-check (good), circle-dash (ok), triangle (watch), diamond (attention), dashed circle (na).

## Portfolio report card (top to bottom)
1. Header: "YOUR MUTUAL FUND CHECK-UP" eyebrow, "Portfolio report card", "N funds · ₹total · Data as of <date>".
   Sample reports add a "Sample data, not a real portfolio" pill. Never print "(sample data) from illustrative sample".
2. The short answer: one sentence from `counts`, plus a single bar of money by verdict with a legend (count, ₹, %).
3. Four checks: tiles "Beat its index?", "Falls less in crashes?", "Rank among similar funds", "What you pay",
   each "X of Y fine" with one segment per fund coloured by status. Replaces the all-amber "at a glance" rows.
4. Each fund at a glance: one row per fund. Columns: fund (name, category, ₹, %), verdict pill, growth
   (5y fund · index · typical fund), in crashes, rank ("Top 25%" etc., never "Q1"), cost (TER · typical).
   "Open →" goes to that fund's card. Horizontal scroll inside the card on phones.
5. Worth a closer look: one box per flagged fund, up to 3 bullet observations and at most 2 questions.
6. Where your money is: bars by category, plus the concentration note when it applies.
7. What we couldn't check: ONE line per fund (e.g. "Fund E is under 2 years old, so only returns and cost are checked").
8. Footer: disclaimer and credits.

## Fund report card (top to bottom)
1. "← All your funds" link. Eyebrow "FUND REPORT CARD", fund name, chips (category, ₹ held and %, "Compared with:
   <index> (TRI) and N <category> funds"), verdict badge on the right.
2. Summary: one sentence plus four tiles (Returns, Ups and downs, Rank among peers, Cost).
3. Panels, two columns on desktop, one on phones:
   - Growth vs its index: 1/3/5y bars for fund, index, typical fund; chips "+x vs index", "+y vs typical";
     "₹1,00,000 five years ago is now …" for all three.
   - When markets rise and fall: "index gained ₹100 → fund ₹108", "index lost ₹100 → fund lost ₹88".
   - Year by year (full width): a tile per year with fund %, index % and margin, typical fund % and margin;
     two summary chips "Beat the index k of n years · avg" and "Beat the typical fund k of n years · avg".
   - Every possible start date: 10 squares, "Beat its index k times in 10".
   - Its worst fall: ₹1,00,000 fell to … for fund, index, typical fund; fall % and months to recover.
   - Rank among N funds: 1/3/5y rows across four boxes Top 25% / Upper middle / Lower middle / Bottom 25%.
   - What you pay: TER vs typical fund, bar with a marker, ₹ a year on the holding.
   - Good to know (full width): risk level, fund size, track record, manager, exit load. No status colours here.
4. Each panel ends with a small "What does … mean?" link to the existing glossary text.
5. Questions: at most 2 per fund, shown once, not repeated under every panel.

Panels with no data are left out, and the gap goes into the one-line "couldn't check" note.

## Engine and pipeline changes this needs
1. Category medians for display (not scored; quartile already measures peer standing):
   - median CAGR at 1, 3, 5 years; median return per calendar year; median worst fall and recovery months.
   - Same category, same plan type (regular/direct), growth option, at least `median_min_funds` (5) funds; otherwise omit.
   - Add to the insight `numbers` (e.g. `by_horizon[].typical`, calendar `typical[]`, drawdown `typical_after`),
     update `docs/report.schema.json`, and test it.
   - Not for index funds: they keep the tracking comparison only.
2. Wording bugs in `calendar_insight`:
   - For a fund behind every year it says "The widest gap was −6.0 points in 2021; the narrowest was −7.0 points in 2022".
     Fix the ordering, and use "fell furthest behind in … / came closest in …" when the margins are negative.
   - "In none of the last 5 calendar years this fund beat …" → "This fund did not beat … in any of the last 5 calendar years."
3. Data gaps: collapse several gaps for one fund into one plain line.
4. Questions: deduplicate, cap at 2 per fund (most severe findings first), show only in the fund's box and the final list.

## Unchanged
Weights, thresholds, verdict rules, the `window.MFAdvisor` contract, the privacy behaviour, and the rule that every
number comes from the engine.
