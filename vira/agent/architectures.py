"""Paper-aligned agent design patterns.

These base classes implement the five coordination topologies evaluated in
*Towards a Science of Scaling Agent Systems* (Kim et al., 2025):

======  ====================  ================================================
Class   Topology              When the paper found it useful
======  ====================  ================================================
``SingleAgent``
        one reasoning locus    Default. Best for sequential, tool-heavy or
                               high-baseline tasks.
``IndependentAgentSystem``
        parallel, no messages  Cheap ensembles; high error amplification.
``CentralizedAgentSystem``
        orchestrator + workers Parallelizable analysis; validation bottleneck
                               contains worker errors.
``DecentralizedAgentSystem``
        peer-to-peer debate     Dynamic, high-entropy search and tool-heavy
                               tasks where parallel exploration helps.
``HybridAgentSystem``
        hierarchy + peer edges Tasks that need both decomposition and lateral
                               review, at the highest coordination cost.
``AdaptiveAgentSystem``
        selection at runtime    Picks one of the above from a ``TaskProfile``.

The paper's practical rules are encoded in :func:`recommend_architecture`:
multi-agent coordination is task-contingent, not a default. For sequential
tasks every multi-agent variant degraded performance by 39–70%, and beyond a
single-agent baseline of ~45% extra coordination usually costs more than it
adds. The classes keep worker counts, rounds and LLM calls bounded.

Authoring::

    from vira.agent.architectures import CentralizedAgentSystem

    class Analyst(CentralizedAgentSystem):
        name = "analyst"
        system_prompt = "You are a careful financial analyst."

    agent = Analyst(runtime, worker_count=3, delegation=False)
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from loguru import logger

from vira.agent.base import TaskRequest, TaskResult
from vira.agent.llm_agent import LLMAgent
from vira.agent.toolcalls import extract_json


class Architecture(str, Enum):
    SINGLE = "single"
    INDEPENDENT = "independent"
    CENTRALIZED = "centralized"
    DECENTRALIZED = "decentralized"
    HYBRID = "hybrid"


#: Coordination characteristics measured in the paper (Table 2/Table 5).
#: ``overhead_pct`` is relative to a matched single-agent token budget and
#: ``error_amplification`` is the observed error factor versus single-agent.
ARCHITECTURE_PROFILES: Dict[Architecture, Dict[str, Any]] = {
    Architecture.SINGLE: {
        "label": "Single agent",
        "topology": "one reasoning locus",
        "coordination": "sequential",
        "llm_calls": "O(k)",
        "parallelism": 1,
        "overhead_pct": 0,
        "error_amplification": 1.0,
        "efficiency": 0.466,
        "summary": "Lowest overhead and no coordination tax; the safe default.",
    },
    Architecture.INDEPENDENT: {
        "label": "Independent agents",
        "topology": "parallel workers, synthesis only",
        "coordination": "synthesis",
        "llm_calls": "O(nk) + synthesis",
        "parallelism": "n",
        "overhead_pct": 58,
        "error_amplification": 17.2,
        "efficiency": 0.234,
        "summary": "Cheap parallelism, but mistakes propagate unchecked.",
    },
    Architecture.CENTRALIZED: {
        "label": "Centralized agents",
        "topology": "orchestrator + isolated workers",
        "coordination": "hierarchical",
        "llm_calls": "O(rnk) + orchestration",
        "parallelism": "n",
        "overhead_pct": 285,
        "error_amplification": 4.4,
        "summary": "Validation bottleneck contains errors; good for decomposable analysis.",
    },
    Architecture.DECENTRALIZED: {
        "label": "Decentralized agents",
        "topology": "peer-to-peer debate",
        "coordination": "consensus",
        "llm_calls": "O(dnk) + synthesis",
        "parallelism": "n",
        "overhead_pct": 263,
        "error_amplification": 7.8,
        "summary": "Parallel exploration and redundancy; useful for dynamic search.",
    },
    Architecture.HYBRID: {
        "label": "Hybrid agents",
        "topology": "orchestrator + peer review",
        "coordination": "hierarchical + lateral",
        "llm_calls": "O(rnk) + peer rounds",
        "parallelism": "n",
        "overhead_pct": 515,
        "error_amplification": 5.1,
        "efficiency": 0.074,
        "summary": "Most flexible and most expensive; reserve for high-value tasks.",
    },
}


@dataclass(frozen=True)
class TaskProfile:
    """Measurable task properties used by the architecture selector.

    Values are intentionally simple and caller-supplied. ``decomposability``
    and ``sequential_dependencies`` are in ``[0, 1]``; ``single_agent_baseline``
    is the expected single-agent accuracy in ``[0, 1]`` if known.
    """

    decomposability: float = 0.5
    sequential_dependencies: float = 0.5
    tool_count: int = 0
    single_agent_baseline: Optional[float] = None
    dynamic_environment: bool = False
    needs_peer_review: bool = False

    @classmethod
    def from_mapping(cls, value: Optional[Dict[str, Any]]) -> "TaskProfile":
        value = value or {}
        return cls(
            decomposability=_to_float(value.get("decomposability"), 0.5),
            sequential_dependencies=_to_float(
                value.get("sequential_dependencies"), 0.5),
            tool_count=max(0, _clamp_int(value.get("tool_count"), 0, 10000, 0)),
            single_agent_baseline=(
                _to_float(value["single_agent_baseline"], 0.0)
                if value.get("single_agent_baseline") is not None else None),
            dynamic_environment=bool(value.get("dynamic_environment", False)),
            needs_peer_review=bool(value.get("needs_peer_review", False)),
        )

    def normalized(self) -> "TaskProfile":
        clamp = lambda value: max(0.0, min(1.0, float(value)))
        baseline = self.single_agent_baseline
        return TaskProfile(
            decomposability=clamp(self.decomposability),
            sequential_dependencies=clamp(self.sequential_dependencies),
            tool_count=max(0, int(self.tool_count)),
            single_agent_baseline=(clamp(baseline) if baseline is not None else None),
            dynamic_environment=bool(self.dynamic_environment),
            needs_peer_review=bool(self.needs_peer_review),
        )


@dataclass(frozen=True)
class ArchitectureRecommendation:
    architecture: Architecture
    confidence: str
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    profile: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "architecture": self.architecture.value,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "profile": dict(self.profile),
            "coordination": dict(ARCHITECTURE_PROFILES[self.architecture]),
        }


def recommend_architecture(task: TaskProfile) -> ArchitectureRecommendation:
    """Choose an architecture using the paper's quantitative rules.

    The order matters: sequential/non-decomposable tasks always select a single
    agent, and tool-heavy tasks may favour decentralized coordination even when
    the single-agent baseline is high (the paper's T=16 example).
    """
    task = task.normalized()
    profile = {
        "decomposability": task.decomposability,
        "sequential_dependencies": task.sequential_dependencies,
        "tool_count": task.tool_count,
        "single_agent_baseline": task.single_agent_baseline,
        "dynamic_environment": task.dynamic_environment,
        "needs_peer_review": task.needs_peer_review,
    }

    if task.sequential_dependencies >= 0.6 or task.decomposability <= 0.35:
        return ArchitectureRecommendation(
            Architecture.SINGLE, "strong",
            reasons=[
                "Sequential or non-decomposable tasks degrade under all tested "
                "multi-agent topologies (−39% to −70%).",
                "A single reasoning locus keeps the full task state in one context.",
            ],
            profile=profile,
        )

    if task.tool_count >= 12:
        return ArchitectureRecommendation(
            Architecture.DECENTRALIZED, "moderate",
            reasons=[
                "Tool-heavy tasks (T≥12) favour parallel exploration and redundancy.",
                "The paper's T=16 example selects decentralized coordination.",
            ],
            warnings=[
                "Coordination overhead is ~263% of a matched single-agent budget.",
            ],
            profile=profile,
        )

    if (task.single_agent_baseline is not None
            and task.single_agent_baseline >= 0.45):
        return ArchitectureRecommendation(
            Architecture.SINGLE, "strong",
            reasons=[
                "Single-agent accuracy is at or above the ~45% capability "
                "ceiling where coordination returns turn negative.",
                "Extra agents mostly add overhead at this baseline.",
            ],
            profile=profile,
        )

    if task.dynamic_environment and task.decomposability >= 0.5:
        return ArchitectureRecommendation(
            Architecture.DECENTRALIZED, "moderate",
            reasons=[
                "Dynamic environments reward parallel exploration and peer exchange.",
                "Decentralized coordination gained +9.2% on web navigation while "
                "centralized was roughly flat.",
            ],
            warnings=["Peer debate is iterative; bound rounds and total tokens."],
            profile=profile,
        )

    if task.needs_peer_review and task.decomposability >= 0.5:
        return ArchitectureRecommendation(
            Architecture.HYBRID, "moderate",
            reasons=[
                "The task needs orchestrated decomposition plus lateral review.",
                "Hybrid combines a validation bottleneck with peer exchange.",
            ],
            warnings=["Hybrid coordination is the most expensive tested topology (~515%)."],
            profile=profile,
        )

    if task.decomposability >= 0.55:
        return ArchitectureRecommendation(
            Architecture.CENTRALIZED, "moderate",
            reasons=[
                "Decomposable analysis benefits from an orchestrator that validates "
                "worker outputs before aggregation.",
                "Centralized coordination improved financial reasoning by +80.9%.",
            ],
            warnings=["Budget roughly 3× the single-agent token cost."],
            profile=profile,
        )

    return ArchitectureRecommendation(
        Architecture.SINGLE, "fallback",
        reasons=[
            "The profile does not show a clear multi-agent win.",
            "The paper's default is a single agent unless task structure justifies coordination.",
        ],
        profile=profile,
    )


WORKER_PROMPT = (
    "You are a focused worker in a {architecture} agent system. You do not see "
    "the other workers' reasoning. Produce a complete, self-contained answer for "
    "the task below. State assumptions and keep the answer concise.\n\n"
    "TASK:\n{task}"
)

ORCHESTRATOR_PROMPT = (
    "You are the orchestrator. Break the task into at most {max_subtasks} "
    "independent, non-overlapping subtasks that can be executed in parallel. "
    "If the task is inherently sequential, return one subtask instead of forcing "
    "a split. Return ONLY JSON: {{\"subtasks\": [\"...\"]}}.\n\n"
    "TASK:\n{task}"
)

VALIDATION_PROMPT = (
    "You are the orchestrator validating one worker result. Check relevance, "
    "completeness and obvious factual or logical errors. Return ONLY JSON: "
    "{{\"ok\": true, \"issue\": \"\", \"revised\": \"\"}}. Set ok to false and "
    "put a corrected answer in revised only when the result is wrong or "
    "incomplete.\n\nTASK:\n{task}\n\nWORKER RESULT:\n{output}"
)

DEBATE_PROMPT = (
    "You are peer {peer} of {total} in a decentralized debate (round {round}). "
    "Review the other peers' answers, correct mistakes, and merge useful "
    "evidence. Return your revised answer only.\n\nTASK:\n{task}\n\n"
    "PEER ANSWERS:\n{answers}"
)

SYNTHESIS_PROMPT = (
    "You are the final synthesizer for a {architecture} agent system. Merge the "
    "worker results into one accurate answer. Prefer claims supported by more "
    "than one worker, and briefly note unresolved disagreements. Do not add "
    "facts that are not supported by the results.\n\nTASK:\n{task}\n\n"
    "RESULTS:\n{results}"
)


def _clamp_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_results(results: Sequence[Dict[str, Any]]) -> str:
    lines = []
    for item in results:
        label = item.get("role") or f"worker {item.get('index', '?')}"
        if item.get("error"):
            lines.append(f"[{label}] ERROR: {item['error']}")
        else:
            lines.append(f"[{label}]\n{item.get('output', '').strip()}")
    return "\n\n".join(lines) or "(no results)"


class ArchitectureAgent(LLMAgent):
    """Common base for the paper's coordination topologies."""

    architecture = Architecture.SINGLE.value

    def __init__(self, runtime, **config: Any):
        super().__init__(runtime, **config)
        merged = dict(config or {})
        self.worker_count = _clamp_int(
            merged.get("worker_count", 3), 1, 8, 3)
        self.max_subtasks = _clamp_int(
            merged.get("max_subtasks", self.worker_count), 1, 8, self.worker_count)
        self.debate_rounds = _clamp_int(
            merged.get("debate_rounds", 1), 0, 3, 1)
        self.validate_outputs = bool(merged.get("validate_outputs", True))
        self.architecture_timeout = float(
            merged.get("architecture_timeout", self.loop_config.max_seconds))
        self.worker_prompt = str(merged.get("worker_prompt") or WORKER_PROMPT)
        self.worker_max_tokens = _clamp_int(
            merged.get("worker_max_tokens", 0), 0, 100000, 0)
        self.orchestrator_prompt = str(
            merged.get("orchestrator_prompt") or ORCHESTRATOR_PROMPT)
        self.validation_prompt = str(
            merged.get("validation_prompt") or VALIDATION_PROMPT)
        self.debate_prompt = str(merged.get("debate_prompt") or DEBATE_PROMPT)
        self.synthesis_prompt = str(
            merged.get("synthesis_prompt") or SYNTHESIS_PROMPT)
        # A mutable list is shared by the child tasks created with gather(),
        # unlike an int stored directly in a ContextVar (which is copied).
        self._calls: ContextVar[Optional[List[int]]] = ContextVar(
            f"architecture_calls_{id(self)}", default=None)

    # --------------------------------------------------------------- selection
    @property
    def architecture_kind(self) -> Architecture:
        try:
            return Architecture(self.architecture)
        except ValueError:
            return Architecture.SINGLE

    def recommend(self, request: TaskRequest) -> Optional[ArchitectureRecommendation]:
        """Override to select an architecture dynamically."""
        return None

    def architecture_for(self, request: TaskRequest) -> Architecture:
        recommendation = self.recommend(request)
        return recommendation.architecture if recommendation else self.architecture_kind

    # ------------------------------------------------------------------ prompts
    def _worker_brief(self, task: str, index: int, total: int) -> str:
        return (
            self.worker_prompt.format(
                architecture=self.architecture,
                task=task,
            )
            + f"\n\nYou are worker {index + 1} of {total}."
        )

    def _synthesis_brief(self, task: str,
                         results: Sequence[Dict[str, Any]]) -> str:
        return self.synthesis_prompt.format(
            architecture=self.architecture,
            task=task,
            results=_format_results(results),
        )

    def _debate_brief(self, task: str, results: Sequence[Dict[str, Any]],
                      index: int, total: int, round_no: int) -> str:
        return self.debate_prompt.format(
            peer=index + 1,
            total=total,
            round=round_no,
            task=task,
            answers=_format_results(results),
        )

    # --------------------------------------------------------------------- LLM
    def _worker_tokens(self) -> int:
        if self.worker_max_tokens:
            return self.worker_max_tokens
        # Keep the total multi-agent budget close to a single-agent budget.
        per_worker = max(192, self.max_tokens // max(1, self.worker_count))
        return per_worker

    def _reset_calls(self) -> None:
        self._calls.set([0])

    def _call_total(self) -> int:
        counter = self._calls.get()
        return counter[0] if counter else 0

    async def _llm(self, prompt: str, *, role: str = "worker",
                   max_tokens: Optional[int] = None) -> str:
        counter = self._calls.get()
        if counter is not None:
            counter[0] += 1
        if self.system_prompt:
            prompt = f"System: {self.system_prompt}\n\n{prompt}"
        self.emit_progress("architecture.llm", architecture=self.architecture,
                           role=role)
        try:
            response = await asyncio.wait_for(
                self.ask_llm(
                    prompt,
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=max_tokens or self._worker_tokens(),
                ),
                timeout=self.architecture_timeout,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"{self.name}: {role} timed out after "
                f"{self.architecture_timeout:.0f}s") from exc
        return str(response or "").strip()

    # ------------------------------------------------------------- worker pools
    async def _run_workers(self, tasks: Sequence[str],
                           request: TaskRequest) -> List[Dict[str, Any]]:
        total = len(tasks)
        prompts = [self._worker_brief(task, index, total)
                   for index, task in enumerate(tasks)]
        results = await asyncio.gather(
            *(self._llm(prompt, role=f"worker-{index + 1}")
              for index, prompt in enumerate(prompts)),
            return_exceptions=True,
        )
        output = []
        for index, value in enumerate(results):
            if isinstance(value, BaseException):
                output.append({
                    "index": index,
                    "role": f"worker-{index + 1}",
                    "task": tasks[index],
                    "output": "",
                    "error": f"{type(value).__name__}: {value}",
                })
            else:
                output.append({
                    "index": index,
                    "role": f"worker-{index + 1}",
                    "task": tasks[index],
                    "output": value,
                    "error": None,
                })
        return output

    async def _synthesize(self, task: str,
                          results: Sequence[Dict[str, Any]],
                          request: TaskRequest) -> str:
        if not any(item.get("output") for item in results):
            details = "; ".join(
                item.get("error", "empty") for item in results) or "no workers"
            raise RuntimeError(f"{self.name}: all workers failed ({details})")
        return await self._llm(
            self._synthesis_brief(task, results),
            role="synthesizer", max_tokens=self.max_tokens)

    # -------------------------------------------------------------- execution
    async def execute(self, request: TaskRequest) -> TaskResult:
        message = request.message
        if not message.strip():
            raise ValueError(f"{self.name} received an empty message")

        recommendation = self.recommend(request)
        kind = (recommendation.architecture if recommendation
                else self.architecture_kind)
        self._reset_calls()
        self.emit_progress("architecture.start", architecture=kind.value,
                           workers=self.worker_count)

        if kind is Architecture.SINGLE:
            result = await super().execute(request)
            result.data["architecture"] = kind.value
            result.data["coordination"] = {
                "architecture": kind.value,
                "workers": 1,
                "rounds": 0,
                "profile": ARCHITECTURE_PROFILES[kind],
                "recommendation": recommendation.as_dict() if recommendation else None,
            }
            return result

        if kind is Architecture.INDEPENDENT:
            data = await self._execute_independent(message, request)
        elif kind is Architecture.CENTRALIZED:
            data = await self._execute_centralized(message, request)
        elif kind is Architecture.DECENTRALIZED:
            data = await self._execute_decentralized(message, request)
        else:
            data = await self._execute_hybrid(message, request)

        data["coordination"]["recommendation"] = (
            recommendation.as_dict() if recommendation else None)
        return TaskResult(
            text=data.pop("text"),
            data={"architecture": kind.value,
                  "coordination": data["coordination"],
                  "workers": data.get("workers", [])},
            steps=data.get("workers", []),
            stopped="final",
        )

    async def _execute_independent(self, message: str,
                                   request: TaskRequest) -> Dict[str, Any]:
        tasks = [message] * self.worker_count
        workers = await self._run_workers(tasks, request)
        final = await self._synthesize(message, workers, request)
        return {
            "text": final,
            "workers": workers,
            "coordination": {
                "architecture": Architecture.INDEPENDENT.value,
                "workers": self.worker_count,
                "rounds": 0,
                "llm_calls": self._call_total(),
                "profile": ARCHITECTURE_PROFILES[Architecture.INDEPENDENT],
            },
        }

    async def _plan(self, message: str, request: TaskRequest) -> List[str]:
        raw = await self._llm(
            self.orchestrator_prompt.format(
                max_subtasks=self.max_subtasks, task=message),
            role="orchestrator", max_tokens=min(512, self.max_tokens))
        plan = extract_json(raw) or {}
        values = plan.get("subtasks") or plan.get("tasks") or []
        subtasks = []
        for value in values if isinstance(values, list) else []:
            text = str(value).strip()
            if text and text not in subtasks:
                subtasks.append(text)
        if not subtasks:
            logger.info("[{}] planner returned no JSON; using one subtask", self.name)
            subtasks = [message]
        return subtasks[:self.max_subtasks]

    async def _validate(self, task: str, item: Dict[str, Any],
                        request: TaskRequest) -> Dict[str, Any]:
        if not self.validate_outputs:
            return item
        if item.get("error") or not item.get("output"):
            return item
        raw = await self._llm(
            self.validation_prompt.format(task=task, output=item["output"]),
            role="validator", max_tokens=min(512, self.max_tokens))
        review = extract_json(raw) or {}
        revised = str(review.get("revised") or "").strip()
        ok = review.get("ok")
        failed = ok is False or str(ok).strip().lower() in {"false", "no", "0"}
        if failed and revised:
            updated = dict(item)
            updated["original_output"] = item["output"]
            updated["output"] = revised
            updated["validation_issue"] = str(review.get("issue") or "")
            return updated
        return item

    async def _validate_all(self, tasks: Sequence[str],
                            workers: Sequence[Dict[str, Any]],
                            request: TaskRequest) -> List[Dict[str, Any]]:
        if not self.validate_outputs:
            return list(workers)
        reviewed = await asyncio.gather(
            *(self._validate(tasks[index], item, request)
              for index, item in enumerate(workers)),
            return_exceptions=True,
        )
        output = []
        for index, value in enumerate(reviewed):
            if isinstance(value, BaseException):
                output.append(workers[index])
            else:
                output.append(value)
        return output

    async def _execute_centralized(self, message: str,
                                   request: TaskRequest) -> Dict[str, Any]:
        tasks = await self._plan(message, request)
        self.emit_progress("architecture.plan", architecture=self.architecture,
                           subtasks=len(tasks))
        workers = await self._run_workers(tasks, request)
        workers = await self._validate_all(tasks, workers, request)
        final = await self._synthesize(message, workers, request)
        corrections = sum(1 for item in workers if item.get("validation_issue"))
        return {
            "text": final,
            "workers": workers,
            "coordination": {
                "architecture": Architecture.CENTRALIZED.value,
                "workers": len(tasks),
                "rounds": 1,
                "subtasks": tasks,
                "validated": self.validate_outputs,
                "corrections": corrections,
                "llm_calls": self._call_total(),
                "profile": ARCHITECTURE_PROFILES[Architecture.CENTRALIZED],
            },
        }

    async def _debate(self, message: str, workers: Sequence[Dict[str, Any]],
                      request: TaskRequest, peer_count: int) -> List[Dict[str, Any]]:
        current = [dict(item) for item in workers]
        for round_no in range(1, self.debate_rounds + 1):
            prompts = [
                self._debate_brief(message, current, index, peer_count, round_no)
                for index in range(peer_count)
            ]
            revised = await asyncio.gather(
                *(self._llm(prompt, role=f"peer-{index + 1}")
                  for index, prompt in enumerate(prompts)),
                return_exceptions=True,
            )
            next_round = []
            for index, value in enumerate(revised):
                if isinstance(value, BaseException):
                    next_round.append(current[index])
                else:
                    next_round.append({
                        "index": index,
                        "role": f"peer-{index + 1}",
                        "task": current[index].get("task", message),
                        "output": value,
                        "error": None,
                        "round": round_no,
                    })
            current = next_round
            self.emit_progress("architecture.debate",
                               architecture=self.architecture, round=round_no)
        return current

    async def _execute_decentralized(self, message: str,
                                     request: TaskRequest) -> Dict[str, Any]:
        tasks = [message] * self.worker_count
        workers = await self._run_workers(tasks, request)
        workers = await self._debate(message, workers, request, self.worker_count)
        final = await self._synthesize(message, workers, request)
        return {
            "text": final,
            "workers": workers,
            "coordination": {
                "architecture": Architecture.DECENTRALIZED.value,
                "workers": self.worker_count,
                "rounds": self.debate_rounds,
                "llm_calls": self._call_total(),
                "profile": ARCHITECTURE_PROFILES[Architecture.DECENTRALIZED],
            },
        }

    async def _execute_hybrid(self, message: str,
                              request: TaskRequest) -> Dict[str, Any]:
        tasks = await self._plan(message, request)
        workers = await self._run_workers(tasks, request)
        workers = await self._validate_all(tasks, workers, request)
        corrections = sum(1 for item in workers if item.get("validation_issue"))
        workers = await self._debate(message, workers, request, len(tasks))
        final = await self._synthesize(message, workers, request)
        return {
            "text": final,
            "workers": workers,
            "coordination": {
                "architecture": Architecture.HYBRID.value,
                "workers": len(tasks),
                "rounds": self.debate_rounds,
                "subtasks": tasks,
                "validated": self.validate_outputs,
                "corrections": corrections,
                "llm_calls": self._call_total(),
                "profile": ARCHITECTURE_PROFILES[Architecture.HYBRID],
            },
        }


class SingleAgent(ArchitectureAgent):
    """One reasoning locus; the recommended default."""

    architecture = Architecture.SINGLE.value


class IndependentAgentSystem(ArchitectureAgent):
    """Parallel workers with no inter-agent communication (synthesis only)."""

    architecture = Architecture.INDEPENDENT.value


class CentralizedAgentSystem(ArchitectureAgent):
    """Orchestrator decomposes, validates and synthesizes isolated workers."""

    architecture = Architecture.CENTRALIZED.value


class DecentralizedAgentSystem(ArchitectureAgent):
    """Peer-to-peer debate with a bounded number of rounds."""

    architecture = Architecture.DECENTRALIZED.value


class HybridAgentSystem(ArchitectureAgent):
    """Hierarchical decomposition plus bounded peer review."""

    architecture = Architecture.HYBRID.value


class AdaptiveAgentSystem(ArchitectureAgent):
    """Select an architecture from a task profile at run time.

    Supply the profile in ``request.metadata["task_profile"]`` or in the agent
    config. Without a profile the selector stays on the single-agent default.
    """

    architecture = Architecture.SINGLE.value

    def _profile(self, request: TaskRequest) -> TaskProfile:
        raw = request.metadata.get("task_profile") if request.metadata else None
        if not isinstance(raw, dict):
            raw = self.config.get("task_profile")
        return TaskProfile.from_mapping(raw if isinstance(raw, dict) else None)

    def recommend(self, request: TaskRequest) -> ArchitectureRecommendation:
        return recommend_architecture(self._profile(request))
