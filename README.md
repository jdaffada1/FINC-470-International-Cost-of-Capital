# FINC 470 — International Cost of Capital

Streamlit application comparing the cost of equity, pretax/after-tax cost of debt, and WACC in USD and a selected country's currency. Based on Sergio Rebelo, *CasePacket2026 Part 9*, slides 564–585 (especially pp. 22–28).

## Quick deployment

1. Upload **all files and the `data/` directory** in this repository to GitHub. `app.py`, `calculations.py`, and `requirements.txt` must remain at the repository root.
2. Visit [Streamlit Community Cloud](https://share.streamlit.io/), choose **Create app** → **Deploy a public app from GitHub**.
3. Select repository `jdaffada1/FINC-470-International-Cost-of-Capital`, branch `main`, main file path `app.py`, and click Deploy.
4. If the app does not start, inspect **Manage app → Logs**. Do not add API keys; the app does not require one.

Run locally with `pip install -r requirements.txt` then `streamlit run app.py`.

## Data sources and freshness

| Input | Source | Included snapshot |
|---|---|---|
| Industry unlevered beta | [Damodaran betas.xls](https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls) | File labeled January 5, 2026; 94 industries |
| Baa2/BBB spread, large nonfinancial firms | [Damodaran ratings](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ratings.htm) | 1.11%, January 2026 |
| Corporate statutory rates | [OECD Corporate Tax Statistics 2026](https://www.oecd.org/en/publications/corporate-tax-statistics-2026_73af6222-en/full-report/statutory-corporate-income-tax-rates_ce84abb9.html) | Selected 2026 rates reproduced in course lecture, page 11 |
| Ten-year government yields | [Trading Economics bonds](https://tradingeconomics.com/bonds) | Course lecture, page 23, yields as of Nov 6, 2026 |

**Refresh button:** Attempts live retrieval from all four public URLs. When a publisher changes page structure, restricts automated requests, or does not expose a machine-readable table, the app keeps the dated snapshot, explicitly reports the failed refresh, and supports manual overrides. **Do not interpret a snapshot as a live quote.** The OECD report page does not reliably expose its complete statutory-rate database as a parseable HTML table; for some countries, users must manually enter a verified rate. This is a limitation of the source, not a fabricated automatic refresh.

The country selector covers countries represented in the professor's 10-year yield table; it is not a claim to include every country in the world. Extend `data/market_snapshots.csv` for additional countries using verified yield, currency and OECD tax information.

## Equations

Rates are stored as decimals internally; percentage inputs are divided by 100.

- `D/E = d/(1-d)`
- `beta_equity = beta_unlevered * (1 + (1-tax) * D/E)`
- `USD_equity = USD_10Y + beta_equity * ERP`
- `USD_debt = USD_10Y + USD_BBB_spread`
- `USD_WACC = (1-d) * USD_equity + d * USD_debt * (1-tax)`
- `F = (1+foreign_10Y)/(1+USD_10Y)`
- `foreign_equity = (1+USD_equity)*F - 1`
- `foreign_BBB_spread = USD_BBB_spread*F` unless manually overridden
- `foreign_debt = foreign_10Y + foreign_BBB_spread`
- `foreign_WACC = (1-d)*foreign_equity + d*foreign_debt*(1-tax)`

The same selected tax rate is applied to both currency scenarios. Currency conversion uses a gross-yield ratio, not a simple difference. The foreign spread override changes **only** foreign-currency debt and WACC.

## Independent verification

Run `python -m unittest discover -s tests -v`. Tests cover the lecture Colombia example, equal yields, zero debt, and foreign spread override independence.

Lecture example: beta_u 0.8, debt 30%, tax 35%, ERP 6.5%, US 10Y 4%, Colombia 10Y 12%, USD BBB spread 1.5%.

Expected values:

| Output | USD | COP |
|---|---:|---:|
| Equity cost | 10.6486% | 19.1600% |
| Pretax debt | 5.5000% | 13.6154% |
| WACC | 8.5265% | 16.0670% |

## Key approximations

U.S. industry beta proxies for project business risk; market portfolio is the U.S. market; no separate country equity premium; government yields proxy for risk-free rates despite sovereign, term and liquidity risk; relative PPP/equal real rates for currency conversion; zero debt beta, fully usable interest tax shields and constant target leverage.

## Repository files

- `app.py` — Streamlit user interface, public-source refresh attempts, overrides and CSV export.
- `calculations.py` — pure calculation engine and benchmark checks.
- `requirements.txt` — deployment dependencies.
- `data/industry_betas.csv` — Damodaran industry snapshot.
- `data/bbb_spread.csv` — credit spread snapshot.
- `data/market_snapshots.csv` — dated course data for selected countries.
- `tests/test_calculations.py` — automated verification.

**Academic note:** The app and tests are AI-assisted. Verify one numerical case independently before submitting, as required by the assignment.
