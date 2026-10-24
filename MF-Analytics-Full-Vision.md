# MF Analytics — Full Vision (Before Scope Tone-Down)

This document captures **everything we were trying to do** with the MF analytics / MFRoboAdvisor direction in its **full form**, before coverage gaps (especially holdings) forced a narrower “MFPRO + supplemental holdings” framing.

Canonical narrowed plan (current): [`MFRoboAdvisor.plan.md`](./MFRoboAdvisor.plan.md)

---

## 1. Starting inspiration

- **TigZig midcap analysis dashboard** — [tigzig.com/midcap-analysis-dashboard](https://www.tigzig.com/midcap-analysis-dashboard)  
  Interactive midcap holdings lens: filter, sort, drilldown (also described as a single-file / Analysis-as-App pattern).
- **TigZig MFPRO** — [tigzig.com/mfpro](https://www.tigzig.com/mfpro), live app [mfpro.tigzig.com](https://mfpro.tigzig.com/)  
  Mutual fund portfolio analytics: holdings, returns, index benchmarks, composition.
- **Product home for build** — `mf-advisor-workbench` (advisor / investor workbench).

Reference UX capture (Returns / risk / drawdown UI claiming **13,000+** schemes):  
`assets/Screenshot_2026-04-16_at_11.05.58_AM-133de96b-7ce4-416c-831b-8d0cfd37a2db.png` (under the Cursor project assets folder used in this chat).

---

## 2. Product name and one-line ambition

**Name:** `MFRoboAdvisor`

**Ambition (full form):** A user (or advisor) pastes or describes their **current mutual fund investments in chat**. The system returns **one client research thread** that always includes:

1. **Overlap**
2. **Peer compare**
3. **Style / concentration**

…powered by **live MF analytics data** (primarily MFPRO), suitable for research and client conversations—not a wandering free-form chat.

---

## 3. Chat intake (full intent)

Accept natural language **or** a short structured paste, then normalize:

| Field | Intent |
| --- | --- |
| **Identifiers** | Scheme names, ISIN, AMFI codes; **fuzzy match** with confirmation when ambiguous |
| **Sizing** | Current value, allocation %, or SIP (+ optional lump sum)—so overlap is **weighted by economic exposure**, not just “same stock appears twice” |
| **Context (optional)** | Goal, horizon, risk tolerance; India equity only vs multi-asset—so peer selection is sensible |

**Validation copy** in the chat UI when schemes can’t be resolved or weights are missing.

---

## 4. Structured research thread (full intent)

Every reply uses a **fixed layout**:

### 4.1 Overlap
- Combined top holdings across the user’s funds  
- Names appearing in **multiple** schemes  
- Estimated **double-count by weight**  
- Concentration in top 5 / top 10 when data allows  

### 4.2 Peer compare
- For each major category held (e.g. midcap active vs index): **2–4 peer funds** with comparable mandate  
- Compare: expense / TER, turnover proxy if available, recent **risk/return labels** (not hype)  
- Explicit “why this peer set was chosen”  
- Leverage MFPRO-style compare: CAGR, rolling returns, risk metrics, drawdown, rolling distribution, benchmark (e.g. Nifty 50)  

### 4.3 Style / concentration
- Category mix (large / mid / small, debt vs equity)  
- Sector / theme tilts implied by holdings  
- Style-box language (growth / value / blend) as **inference from data**, with uncertainty called out  

### 4.4 Close of every thread
- **Assumptions and limits**  
- Data **as-of** dates  
- What was inferred vs verified  
- Clear line that numbers are **not** a buy/sell recommendation  

---

## 5. High-level flow (full intent)

```text
User portfolio message
  → Parse and normalize schemes
  → Fetch holdings + metadata + returns/risk
  → Section: Overlap
  → Section: Peer compare
  → Section: Style / concentration
  → Assumptions, as-of, disclaimer
```

---

## 6. Data & “database” ambition (full form)

### 6.1 Primary connection: MFPRO as the fund analytics database

Connect MFRoboAdvisor to MFPRO for **all relevant fund analytics**:

| Surface | Role |
| --- | --- |
| [tigzig.com/mfpro](https://www.tigzig.com/mfpro) | Product entry |
| [mfpro.tigzig.com](https://mfpro.tigzig.com/) | Live analytics (Returns + Composition, SIP, TER, Category, Fund, …) |
| [mfpro.tigzig.com/data-api](https://mfpro.tigzig.com/data-api) | NAV downloads + REST API (JSON), full DB export formats (CSV / TSV / Parquet / SQLite) |

**Live UI claim we wanted to rely on:**  
CAGR, rolling returns, risk metrics, and drawdown across **13,000+** mutual fund schemes and indices—plus tabs for Composition, SIP, TER, Category, Fund, Data & API, Status, Docs, validation, download.

### 6.2 What we wanted out of MFPRO for every section

| Plan need | Full ambition |
| --- | --- |
| Returns / risk / drawdown | Point-to-point, rolling (30D–5Y), risk metrics, drawdown, multi-fund vs index |
| Peer compare | Peers from same category / mandate; TER; return & risk labels; benchmark-relative narrative |
| Overlap | Security-level holdings across **whatever schemes the user typed** |
| Style / concentration | Sectors, themes, top-10 concentration from holdings |
| Fund vs Nifty benchmarks | Holdings vs Nifty 50 / 100 / 500 / Midcap, etc. |
| Scheme metadata | TER, category, enough labels for peer copy |
| Freshness | As-of dates, Status page, automated sync |
| Automation | Programmatic pull via **Data & API** / Swagger for the chat backend |

### 6.3 Supporting TigZig MF tooling (discovery via [llms.txt](https://tigzig.com/llms.txt))

Not the core “database,” but part of the **full toolbox** we were mapping:

- Midcap Analysis Dashboard  
- AI MF Processor (`mf-files-ai`) — disclosure Excel → CSV/TXT  
- MDRIFT — composition & drift (curated funds)  
- MF Portfolio Processor (xlwings) — two-period holdings, ISIN mapping  
- MF Holdings Analyzer GPT / MF Portfolio Analyzer GPT  
- Blog / AI docs under tag `mutual-funds`  

**Machine-readable site content** (from `llms.txt`) we noted for discovery, not for NAV/holdings rows:

- `llms.txt`, `llms-full.txt`  
- `ai/index.md`, `ai/apps/{slug}.md`, `ai/posts/{slug}.md`, `ai/tags/{topic}.md`  
- `search-index.json`, `blog-index.json`  
- Static HTML posts/docs, `sitemap.xml`, `feed.xml`  
- `POST /api/ai-feedback`  

---

## 7. Advisor / research workflow (manual + product)

Even in the full vision, humans could use TigZig dashboards the same way the product would automate:

1. Pick intent: overlap / style drift / peer compare  
2. Filter, sort, drilldown on holdings or returns views  
3. Generate questions from the dashboard  
4. Confirm with **AMC factsheet / SID** before advice  
5. Record as-of dates and exports for audit  

Manual preference:

- Midcap dashboard → category- and holdings-specific midcap peers  
- MFPRO → returns, benchmarks, composition, broader compare  

---

## 8. Build-time decisions (full checklist)

Originally tracked as **five todos under one plan (`MFRoboAdvisor`)**:

1. **define-use-case** — Per client / research thread: overlap, peer compare, or style/concentration (product later made all three default in one thread).  
2. **cross-check-official** — Verify key holdings/weights against AMC factsheet or scheme docs before advice.  
3. **chat-intake-schema** — Minimal portfolio message format + validation copy.  
4. **structured-response-template** — Fixed reply layout with bullets, tables, as-of dates.  
5. **data-pipeline-disclaimers** — Choose sources, refresh cadence, user-facing disclaimer; integrate MFPRO app + data-api; rate limits / beta; commercial-use terms.

Additional build decisions named in discussion:

- **Peers:** Rule-based (same AMFI category + similar benchmark) + human-overridable lists for advisors  
- **Compliance:** Jurisdiction-specific copy; log inputs/outputs if license requires auditability  
- **Rate limits:** e.g. NAV API ~100 req/min per IP (as publicly stated)  
- **Beta:** Expect breaking changes on data-api  

---

## 9. What “toning it down” changed

The **product UX ambition** (chat → three-section research thread) stayed. What narrowed was **assuming MFPRO alone is a complete database for every scheme**:

| Area | Full ambition | After tone-down |
| --- | --- | --- |
| Returns / risk / drawdown | Use MFPRO at **13,000+** scale for nearly any India scheme the user names | Still primary; reconcile API vs UI counts at integration |
| Peer compare (returns/risk) | Broad peer sets from MFPRO universe | Prefer peers **inside** MFPRO coverage; document gaps |
| Overlap (security-level) | Across **any** user fund list via MFPRO Composition | **Not guaranteed** for all schemes; verify Composition coverage; **supplement** holdings (disclosures / factsheets) when missing |
| Style / concentration from holdings | Same as overlap | Same gap; don’t promise from the 13,000+ returns headline alone |
| Factsheet-complete metadata | Assumed “all relevant” from MFPRO | **Do not assume**; keep AMC factsheet / SID path |
| User portfolio weights | — | Always from **chat**, never from MFPRO |

**Working conclusion after research:**  
MFPRO is excellent as the **primary returns/risk/compare engine** and as a **Composition source where coverage exists**, but **not** a sole source for unconstrained holdings-based overlap and style for every Indian scheme.

---

## 10. Explicit non-goals (always)

- Not investment advice or a substitute for suitability analysis  
- Not scraping SPA HTML as the integration path (prefer Data & API / documented endpoints; use `llms.txt` for docs discovery only)  
- Not redistributing TigZig data beyond what their terms allow  

---

## 11. One-sentence “full vision” summary

**Build an MFRoboAdvisor chat in mf-advisor-workbench that turns a user’s mutual fund portfolio into a dated research thread—Overlap, Peer compare, Style/concentration—backed by MFPRO’s 13,000+ scheme returns/risk stack and Composition where available, with official documents and supplemental holdings filling gaps, and clear non-advice disclaimers.**
