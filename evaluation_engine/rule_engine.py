"""Deterministic rule engine for state-machine transitions.

Rules are pure callables ``(context: dict) -> bool``.  The engine evaluates
a target state by running its registered rule against a provided context.
"""
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    passed: bool
    reason: str
    state: str


class RuleEngine:
    def __init__(self, rules: Optional[Dict[str, Callable[[Dict[str, Any]], bool]]] = None) -> None:
        self._rules = dict(rules) if rules else {}

    def register_rule(self, rule_id: str, evaluator: Callable[[Dict[str, Any]], bool]) -> None:
        self._rules[rule_id] = evaluator

    def evaluate(self, context: Dict[str, Any], target_state: str) -> RuleResult:
        evaluator = self._rules.get(target_state)
        if evaluator is None:
            return RuleResult(
                rule_id=target_state,
                passed=False,
                reason=f"No rule registered for state {target_state}",
                state=target_state,
            )
        try:
            passed = bool(evaluator(context))
        except Exception as exc:
            return RuleResult(
                rule_id=target_state,
                passed=False,
                reason=f"Rule evaluation error: {exc}",
                state=target_state,
            )
        return RuleResult(
            rule_id=target_state,
            passed=passed,
            reason="Rule passed" if passed else "Rule failed",
            state=target_state,
        )
