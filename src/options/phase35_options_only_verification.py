"""Phase 35, Part B/T — verifies that the frozen
`MomentumBreakoutStrategy` can only ever produce an options order, by
tracing its real, complete execution path (never by assumption).

FULL TRACE (every hop cited by file:line as of this phase):

  1. `MomentumBreakoutStrategy._scan_symbol` (momentum_breakout.py:92-165)
     never reads or emits a raw stock symbol as a tradable target -- the
     underlying `symbol` argument is used ONLY to look up bars/quotes and
     to resolve an option chain; the thing actually returned is a
     `SetupCandidate` whose `option_id` field (momentum_breakout.py:154)
     came from `_select_contract` (momentum_breakout.py:167-198), itself
     built entirely from `raw.get("id")` values returned by
     `market.get_option_chain_candidates(..., type="call", ...)`
     (momentum_breakout.py:174-180) -- a call filtered exclusively to
     option instruments, never equity instruments.
  2. `SetupCandidate.__post_init__` (strategy/base.py:44-46) hard-rejects
     any `side` other than `"long_call"`/`"long_put"` at construction --
     there is no equity-share `side` value this dataclass can represent.
  3. `orchestrator.py::_submit_entry_order` (orchestrator.py:432-455)
     builds exactly one `OrderLeg(option_id=candidate.option_id, ...)`
     (orchestrator.py:441) -- `option_id` is a REQUIRED, non-optional
     field on `OrderLeg` (orders.py:47); there is no shares/quantity-of-
     stock field on `OrderLeg` or `OrderRequest` for this call to
     populate even if it wanted to.
  4. `execution_gateway.submit_order(order)` (orchestrator.py:455) is the
     only thing this call site can do with the resulting `OrderRequest`
     -- `PaperExecutionGateway`/`LiveExecutionGateway` both operate on
     that exact dataclass shape; neither has (or could have) a code path
     that inspects `chain_symbol`/`underlying_type` (the two STRING
     metadata fields that DO carry a raw symbol -- orders.py:89-90) to
     decide what to submit. Those two fields are audit/fee-context-only
     metadata passed through to `review_option_order` for informational
     purposes (orders.py:89 comment) -- never read anywhere to construct
     or redirect an order. `_place_pending` (gateway.py:297-353) calls
     `place_option_order(legs=[leg.to_dict() for leg in order.legs], ...)`
     (gateway.py:314-324) -- only `option_id`-bearing legs, never a raw
     symbol.

CONCLUSION: no equity `OrderLeg` can be produced by this strategy or by
anything downstream of it (structurally, not merely by convention), and
there is no "conversion boundary" to document -- the strategy selects a
SPECIFIC OPTION CONTRACT (`option_id`) at scan time, before any
`OrderRequest` is ever built; no layer downstream ever converts an
underlying symbol into an option, because no underlying symbol ever
reaches the order-construction step as anything but already-consumed
context (used to fetch quotes/bars/chains, then discarded).

FIELD-BY-FIELD VERIFICATION (Part B's explicit checklist):
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OptionsOnlyVerificationResult:
    option_id_mandatory: bool
    option_id_mandatory_evidence: str
    option_type_explicit: bool
    option_type_explicit_evidence: str
    expiration_explicit: bool
    expiration_explicit_evidence: str
    strike_explicit: bool
    strike_explicit_evidence: str
    no_equity_order_leg_possible: bool
    no_equity_order_leg_evidence: str
    conversion_boundary_exists: bool
    conversion_boundary_note: str
    blocker_found: bool


VERIFICATION = OptionsOnlyVerificationResult(
    option_id_mandatory=True,
    option_id_mandatory_evidence=(
        "OrderLeg.option_id (execution/orders.py) is a required, non-optional str field -- "
        "no default, no None allowed at the type level; every construction site in the live "
        "path (orchestrator.py:441, position_manager/monitor.py's closing-order builder) "
        "passes a real option_id sourced from a prior option-chain lookup."
    ),
    option_type_explicit=True,
    option_type_explicit_evidence=(
        "Encoded in SetupCandidate.side (hard-validated to 'long_call'/'long_put', "
        "strategy/base.py:44-46) and requested explicitly as type='call' in the live "
        "get_option_chain_candidates call (momentum_breakout.py:178) -- MomentumBreakoutStrategy "
        "is calls-only by construction (its own module docstring: 'Scope, deliberately: CALLS ONLY'). "
        "Not a dedicated structured field on OrderRequest/OrderLeg -- the broker resolves it from "
        "the specific option_id instrument."
    ),
    expiration_explicit=True,
    expiration_explicit_evidence=(
        "SetupCandidate.expiration is a dedicated `date` field (strategy/base.py), populated by "
        "_select_expiration's DTE-window filter (momentum_breakout.py:200-206) and carried through "
        "to OpenPosition.expiration (position_manager/models.py) -- used directly for expiration-risk "
        "exit logic and minutes_to_expiration."
    ),
    strike_explicit=True,
    strike_explicit_evidence=(
        "Not a dedicated structured numeric field on SetupCandidate/OrderRequest/OrderLeg -- but "
        "fully and unambiguously determined by the selected option_id (a specific broker instrument "
        "UUID resolved from real chain candidates in _select_contract, momentum_breakout.py:182-198) "
        "and human-readably recorded in SetupCandidate.option_description (e.g. 'AAPL 2026-09-18 C 230', "
        "momentum_breakout.py:155). No ambiguity reaches the order gateway: option_id alone fully "
        "specifies strike/expiration/type at the broker."
    ),
    no_equity_order_leg_possible=True,
    no_equity_order_leg_evidence=(
        "place_equity_order/review_equity_order/cancel_equity_order have zero call sites anywhere "
        "in src/ (re-confirmed this phase, Phase 34's independent finding unchanged); OrderLeg/"
        "OrderRequest have no shares/equity-symbol field to populate even in principle."
    ),
    conversion_boundary_exists=False,
    conversion_boundary_note=(
        "No conversion boundary exists because none is needed: the strategy selects a specific "
        "option contract (option_id) at scan time, before any OrderRequest is constructed. No "
        "underlying symbol is ever converted into an option downstream -- chain_symbol/"
        "underlying_type on OrderRequest are audit-context metadata only (orders.py:89-90), never "
        "read to construct or redirect an order."
    ),
    blocker_found=False,
)
