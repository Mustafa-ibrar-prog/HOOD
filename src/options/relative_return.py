"""Phase 22, Part 6 (Theme A/D) — OPTION_UNDERLYING_RELATIVE_RETURN: an
explicitly-labeled, explicitly-limited comparison of an option's own
return to its underlying's return, WITHOUT using any historical Greek
(none exist for this data source -- see Part 2/10's prohibition on
reconstructing one and pretending it was observed).

`rolling_beta` here is a purely EMPIRICAL, REALIZED linear sensitivity
of a contract's own daily returns to its underlying's daily returns
over a trailing window -- a plain OLS slope (cov/var) of two observed
return series. It is NOT delta: delta is a risk-neutral, model-derived,
INSTANTANEOUS sensitivity that would require an options pricing model
and current Greeks to compute; this is neither. It captures "how has
THIS PARTICULAR CONTRACT actually tended to move alongside its
underlying recently" and nothing more. Treat every function in this
module as a coarse, backward-looking descriptive statistic, not a risk
measure.

`OPTION_UNDERLYING_RELATIVE_RETURN` (the naive and beta-scaled excess
functions below) inherits the same limitation: it is a return residual
against an empirically-observed relationship, not a delta-hedged P&L
and not a claim about what a market-maker's risk-neutral pricing model
would say the option "should" have done.
"""

from __future__ import annotations

from typing import Sequence


def rolling_beta(option_returns: Sequence[float | None], underlying_returns: Sequence[float | None], window: int) -> list[float | None]:
    """out[i] = the OLS slope of `option_returns` on `underlying_returns`
    over the trailing `window` PAIRED observations ending at (and
    including) index i -- cov(option, underlying) / var(underlying) over
    that window. None wherever either series has fewer than `window`
    non-None values ending at i, or the underlying's variance is 0 over
    that window (a degenerate/flat underlying -- no slope is defined).
    A purely empirical, realized quantity -- see the module docstring
    for what this is NOT."""
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")
    if len(option_returns) != len(underlying_returns):
        raise ValueError("option_returns and underlying_returns must be the same length")
    n = len(option_returns)
    out: list[float | None] = []
    for i in range(n):
        if i < window - 1:
            out.append(None)
            continue
        opt_window = option_returns[i - window + 1: i + 1]
        und_window = underlying_returns[i - window + 1: i + 1]
        if any(v is None for v in opt_window) or any(v is None for v in und_window):
            out.append(None)
            continue
        mean_opt = sum(opt_window) / window
        mean_und = sum(und_window) / window
        cov = sum((o - mean_opt) * (u - mean_und) for o, u in zip(opt_window, und_window)) / window
        var_und = sum((u - mean_und) ** 2 for u in und_window) / window
        if var_und == 0:
            out.append(None)
            continue
        out.append(cov / var_und)
    return out


def naive_excess_return(option_return: float | None, underlying_return: float | None) -> float | None:
    """OPTION_UNDERLYING_RELATIVE_RETURN, naive/unscaled form:
    option_return - underlying_return. The simplest possible "did the
    option do better or worse than its underlying, in raw % terms"
    comparison -- deliberately makes NO attempt to account for
    convexity, moneyness, or sensitivity; a call deep ITM and a call
    deep OTM are compared on exactly the same footing here, which is
    this form's acknowledged limitation (the beta-scaled form below is
    the attempt at a fairer comparison, itself limited too)."""
    if option_return is None or underlying_return is None:
        return None
    return option_return - underlying_return


def beta_scaled_excess_return(option_return: float | None, underlying_return: float | None, beta: float | None) -> float | None:
    """OPTION_UNDERLYING_RELATIVE_RETURN, beta-scaled form:
    option_return - beta * underlying_return, where `beta` is a
    `rolling_beta` estimate (see module docstring: an empirical realized
    slope, NOT delta). Still not risk-neutral, still not a claim about
    what the option "should" have returned -- only "relative to its OWN
    recently observed empirical sensitivity, did the option do better or
    worse than that sensitivity alone would explain.\""""
    if option_return is None or underlying_return is None or beta is None:
        return None
    return option_return - beta * underlying_return
