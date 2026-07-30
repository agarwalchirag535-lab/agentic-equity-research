# PRIOR_ART.md — Open-source survey (SPEC §10)

Rule: **study, don't fork.** Lift specific design patterns; adopt none wholesale. Verified against the
current (2026) state of each project.

## Multi-agent finance frameworks

### AI4Finance-Foundation/FinRobot — closest prior art
Four-layer platform (Financial AI Agents / Financial LLM Algorithms / LLMOps+DataOps / foundation
models) with a "Smart Scheduler" routing tasks to the most suitable model. Enforces separation between
deterministic financial computation and LLM narration — this *is* our Law 1.
- **Steal:** the compute/narration separation as proof-of-pattern; the model-routing idea for
  `config/models.yaml`.
- **Avoid:** its platform breadth. We want a focused, gated pipeline, not a toolkit.

### TauricResearch/TradingAgents
Multi-agent firm mirror; fundamental/sentiment/technical analysts feed a trader + risk team, and agents
**debate** to a strategy.
- **Steal:** the bull/bear debate structure — wire it into `red_team` ⇄ `thesis_synthesizer`.
- **Avoid:** the entire trading-execution layer (violates SPEC §1's hard boundary).

### virattt/ai-hedge-fund (~43k–50k★, very active in 2026)
~18 persona agents (each an investor archetype) + a risk manager computing position limits + a portfolio
manager synthesising signals. Trades are simulated only.
- **Steal:** the agent → portfolio-manager plumbing and position-sizing pattern for `portfolio_manager`.
- **Avoid:** the "invest like famous investor X" personas — vibes, not evidence chains; they clash with
  our numbers-over-adjectives house style.

### Indexes to mine for anything newer than this spec
`LLMQuant/awesome-trading-agents`, `Tom-roujiang/Awesome-LLM-Quantitative-Trading-Papers`. Also note a
Korea-market equity-research framework already ships an *analyze → verify → reflect* self-improvement
loop — our SPEC §7 is becoming standard, not exotic.

## Data / infra patterns
- **OpenBB** — study its provider-abstraction and data-adapter patterns for `core/llm/provider.py` and
  `adapters/base/`, even though its India coverage is thin.
- **Look-Ahead-Bench (arXiv)** — read before building the eval harness. Look-ahead-bias contamination is
  the standard failure mode of exactly this class of system; it justifies Law 3.

## India data plumbing (grade + note; all go behind `adapters/india/`)
| Library | Use | 2026 status / note |
|---|---|---|
| `jugaad-data` | NSE stock/index/derivative, bhavcopy, RBI | Healthiest choice — targets the *new* NSE site (many libs still hit the dead old one), has NSE-friendly caching, still receiving fixes in 2026 |
| `nsepython` / `nselib` | NSE quotes, corporate info | Works but brittle to NSE site changes; keep behind adapter |
| `bse` (BseIndiaApi), `pnsea` | BSE announcements/filings | Useful for filings feed; verify freshness per run |
| AMFI | mutual-fund holdings | Source of record for MF holdings (`ownership_flows_analyst`) |
| BSE/NSE announcement feeds | filings + transcripts triggers | Primary trigger source for bronze ingestion |

**Hard lesson baked into the plan:** these libraries break whenever exchanges change their sites, and
they give *current* data, not archived point-in-time filings. Every one sits behind an adapter interface
so a dead library is a one-file fix — and the 10-yr / point-in-time history (PLAN OQ#1) will need a
filings/annual-report archive beyond these exchange libraries.

## Sources
- [FinRobot (GitHub)](https://github.com/ai4finance-foundation/finrobot) ·
  [FinRobot paper](https://arxiv.org/pdf/2405.14767)
- [ai-hedge-fund writeup](https://blogs.reskilll.com/ai-hedge-fund-the-50k-star-open-source-multi-agent-investment-system/) ·
  [18-agents overview](https://converter.brightcoding.dev/blog/ai-hedge-fund-18-agents-that-think-like-legendary-traders)
- [AI in Quantitative Investment — survey](https://arxiv.org/pdf/2503.21422)
- [jugaad-data (GitHub)](https://github.com/jugaad-py/jugaad-data) ·
  [nselib (PyPI)](https://pypi.org/project/nselib/)
- [Beneish M-score effectiveness on Indian firms/banks (ResearchGate)](https://www.researchgate.net/publication/392336805_Assessing_the_effectiveness_of_the_Beneish_M-Score_Model_to_Detect_Financial_Manipulation_in_Selected_Indian_Public_and_Private_Banks)
