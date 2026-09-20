"""Review orchestrator that coordinates rule evaluation and LLM analysis,
emitting an immutable audit entry for every task it processes."""
from dataclasses import asdict
from typing import Any, Dict, Optional

from evaluation_engine.rule_engine import RuleEngine, RuleResult
from integrations.local_llm_client import LLMRequest, LocalLLMClient
from services.crypto_audit_emitter import CryptoAuditEmitter


class ReviewOrchestrator:
    def __init__(
        self,
        rule_engine: RuleEngine,
        llm_client: Optional[LocalLLMClient] = None,
        audit_emitter: Optional[CryptoAuditEmitter] = None,
    ) -> None:
        self.rule_engine = rule_engine
        self.llm_client = llm_client
        self.audit_emitter = audit_emitter or CryptoAuditEmitter()

    def evaluate_task(
        self,
        task_id: str,
        context: Dict[str, Any],
        target_state: str,
        actor: str = "system",
        timestamp: Optional[str] = None,
    ) -> Dict[str, Any]:
        rule_result: RuleResult = self.rule_engine.evaluate(context, target_state)
        llm_result: Optional[str] = None
        if self.llm_client and self.llm_client.is_configured():
            try:
                response = self.llm_client.analyze(
                    LLMRequest(
                        prompt=f"Analyze task {task_id} for state {target_state}",
                        context=context,
                    )
                )
                llm_result = response.result
            except Exception as exc:
                llm_result = f"LLM call failed: {exc}"
        self.audit_emitter.emit(
            event_type="task_evaluation",
            actor=actor,
            payload={
                "task_id": task_id,
                "target_state": target_state,
                "rule_result": asdict(rule_result),
                "llm_result": llm_result,
            },
            timestamp=timestamp,
        )
        return {
            "task_id": task_id,
            "rule_result": rule_result,
            "llm_result": llm_result,
        }
