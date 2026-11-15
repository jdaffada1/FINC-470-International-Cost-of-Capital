"""FINC 470 lecture methodology. All rates are decimals (0.065 = 6.5%)."""
from dataclasses import dataclass, asdict

@dataclass(frozen=True)
class Result:
    beta_unlevered: float
    beta_equity: float
    debt_to_equity: float
    tax_rate: float
    factor: float
    usd_equity: float
    usd_debt: float
    usd_debt_after_tax: float
    usd_wacc: float
    foreign_equity: float
    foreign_spread: float
    foreign_debt: float
    foreign_debt_after_tax: float
    foreign_wacc: float


def calculate(beta_u: float, debt_share: float, tax: float, erp: float,
              rf_us: float, rf_foreign: float, spread_us: float,
              foreign_spread_override: float | None = None) -> Result:
    if not (0 <= debt_share < 1):
        raise ValueError('Debt share must be between 0% and less than 100%.')
    if not (0 <= tax <= 1):
        raise ValueError('Tax rate must be between 0% and 100%.')
    if rf_us <= -1 or rf_foreign <= -1:
        raise ValueError('Government yields must exceed -100%.')
    if beta_u < 0 or erp < 0 or spread_us < 0 or (foreign_spread_override is not None and foreign_spread_override < 0):
        raise ValueError('Beta, ERP and credit spreads must be nonnegative.')
    de = debt_share / (1 - debt_share)
    beta_e = beta_u * (1 + (1 - tax) * de)
    re_us = rf_us + beta_e * erp
    rd_us = rf_us + spread_us
    wacc_us = (1 - debt_share) * re_us + debt_share * rd_us * (1 - tax)
    factor = (1 + rf_foreign) / (1 + rf_us)
    re_fx = (1 + re_us) * factor - 1
    spread_fx = spread_us * factor if foreign_spread_override is None else foreign_spread_override
    rd_fx = rf_foreign + spread_fx
    wacc_fx = (1 - debt_share) * re_fx + debt_share * rd_fx * (1 - tax)
    return Result(beta_u, beta_e, de, tax, factor, re_us, rd_us, rd_us * (1-tax), wacc_us,
                  re_fx, spread_fx, rd_fx, rd_fx * (1-tax), wacc_fx)


def verify() -> dict[str, bool]:
    p = dict(beta_u=.8, debt_share=.3, tax=.35, erp=.065, rf_us=.04, rf_foreign=.12, spread_us=.015)
    a = calculate(**p)
    # Benchmarks from lecture pages 25–28, tolerances reflect four-decimal display.
    benchmark = all(abs(v - t) < 0.0000006 for v, t in [
        (a.beta_equity, 1.022857142857), (a.usd_equity, .106485714286),
        (a.usd_wacc, .085265), (a.foreign_equity, .1916),
        (a.foreign_debt, .136153846154), (a.foreign_wacc, .16067)])
    eq = calculate(**{**p, 'rf_foreign': p['rf_us']})
    equal_yields = abs(eq.usd_wacc-eq.foreign_wacc) < 1e-12 and abs(eq.usd_equity-eq.foreign_equity)<1e-12
    zero = calculate(**{**p,'debt_share':0})
    zero_debt = abs(zero.usd_wacc-zero.usd_equity)<1e-12 and abs(zero.foreign_wacc-zero.foreign_equity)<1e-12
    override = calculate(**p, foreign_spread_override=.04)
    override_independent = abs(override.usd_wacc-a.usd_wacc)<1e-12 and abs(override.usd_equity-a.usd_equity)<1e-12 and abs(override.foreign_wacc-a.foreign_wacc)>1e-6
    return {'Colombia lecture benchmark':benchmark,'Equal yields':equal_yields,'Zero debt':zero_debt,'Foreign spread override independence':override_independent}
