from app.recommendation.rules import resource_rules, threshold_rules, waste_rules  # noqa: F401
from app.recommendation.rules.base import (
    RULES,
    ContainerAnalysis,
    RuleFinding,
    RuleThresholds,
    register,
)

__all__ = ["RULES", "ContainerAnalysis", "RuleFinding", "RuleThresholds", "register"]


def evaluate(analysis: ContainerAnalysis, thresholds: RuleThresholds) -> list[RuleFinding]:
    findings = [rule(analysis, thresholds) for rule in RULES]
    return [finding for finding in findings if finding is not None]
