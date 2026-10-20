# vira/agent_orchestration/metrics.py
class AgentMetrics:
    def __init__(self, metrics_manager):
        self._metrics = metrics_manager

    def record_agent_start(self, agent_id: str):
        self._metrics.increment_counter("agent_starts_total", labels={"agent_id": agent_id})

    def record_agent_completion(self, agent_id: str, duration: float, success: bool):
        self._metrics.observe_histogram("agent_execution_seconds", duration, labels={"agent_id": agent_id})
        status = "success" if success else "failure"
        self._metrics.increment_counter("agent_completions_total", labels={"agent_id": agent_id, "status": status})

    def record_llm_call(self, model: str, tokens: int, cost: float):
        self._metrics.increment_counter("llm_tokens_total", tokens, labels={"model": model})
        self._metrics.increment_counter("llm_cost_total", cost, labels={"model": model})