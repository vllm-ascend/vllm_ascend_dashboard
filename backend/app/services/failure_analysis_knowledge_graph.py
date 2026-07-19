"""Build a frontend-ready knowledge graph from a failure analysis record.

The graph is intentionally derived from persisted analysis evidence instead of
re-running the agent. It is a diagnostic view: if a hypothesis has weak links to
logs/code/validation, that weakness should be visible instead of hidden.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from app.models import JobFailureAnalysis


def build_failure_analysis_knowledge_graph(analysis: JobFailureAnalysis) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    edge_ids: set[str] = set()

    def add_node(
        node_id: str,
        node_type: str,
        label: str,
        *,
        title: str | None = None,
        subtitle: str | None = None,
        status: str | None = None,
        confidence: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> str:
        if node_id in node_ids:
            return node_id
        node_ids.add(node_id)
        nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "label": _clip(label, 96),
                "title": _clip(title, 180) if title else None,
                "subtitle": _clip(subtitle, 220) if subtitle else None,
                "status": status,
                "confidence": confidence,
                "data": data or {},
            }
        )
        return node_id

    def add_edge(
        source: str,
        target: str,
        edge_type: str,
        label: str,
        *,
        data: dict[str, Any] | None = None,
    ) -> None:
        edge_id = f"{source}->{edge_type}->{target}"
        if edge_id in edge_ids:
            return
        edge_ids.add(edge_id)
        edges.append(
            {
                "id": edge_id,
                "source": source,
                "target": target,
                "type": edge_type,
                "label": label,
                "data": data or {},
            }
        )

    ledger = _as_dict(analysis.evidence_ledger)
    validation = _as_dict(analysis.validation_result)
    trace = _as_list(analysis.agent_trace)

    analysis_node = add_node(
        f"analysis:{analysis.id}",
        "analysis",
        f"Analysis #{analysis.id}",
        title=analysis.root_cause_summary or analysis.error_message or "Failure analysis",
        subtitle=f"{analysis.analysis_status or 'unknown'} / {analysis.analysis_phase or 'unknown'}",
        status=analysis.analysis_status,
        data={
            "job_id": analysis.job_id,
            "run_id": analysis.run_id,
            "problem_category": analysis.problem_category,
            "agent_steps": analysis.agent_steps,
            "llm": "/".join(x for x in [analysis.llm_provider, analysis.llm_model] if x),
        },
    )
    job_node = add_node(
        f"job:{analysis.job_id}",
        "job",
        analysis.job_name or f"Job {analysis.job_id}",
        subtitle=f"run {analysis.run_id}",
        status="failed",
        data={"workflow_name": analysis.workflow_name, "failure_date": str(analysis.failure_date)},
    )
    workflow_node = add_node(
        f"workflow:{_safe_key(analysis.workflow_name)}",
        "workflow",
        analysis.workflow_name or "workflow",
    )
    add_edge(analysis_node, job_node, "ANALYZES", "分析对象")
    add_edge(job_node, workflow_node, "IN_WORKFLOW", "所属 workflow")

    for idx, fact in enumerate(_as_list(ledger.get("failure_facts"))[:12], start=1):
        fact_text = _stringify(fact)
        fact_node = add_node(f"fact:{idx}", "failure_fact", f"失败事实 {idx}", title=fact_text)
        add_edge(analysis_node, fact_node, "HAS_FACT", "失败事实")

    boundary = _as_dict(ledger.get("regression_boundary") or ledger.get("commit_boundary"))
    for key, label in [("bad_sha", "坏提交"), ("last_good_sha", "上次成功提交"), ("good_sha", "成功提交")]:
        sha = boundary.get(key)
        if sha:
            commit_node = add_node(
                f"commit:{key}:{str(sha)[:12]}",
                "commit",
                f"{label}: {str(sha)[:12]}",
                title=str(sha),
                status=key,
            )
            add_edge(analysis_node, commit_node, key.upper(), label)

    hypotheses = _as_list(ledger.get("hypotheses"))
    for idx, hypothesis in enumerate(hypotheses[:10], start=1):
        hyp = _as_dict(hypothesis)
        hyp_id = str(hyp.get("id") or f"H{idx}")
        hyp_node = add_node(
            f"hypothesis:{_safe_key(hyp_id)}",
            "hypothesis",
            hyp_id,
            title=_stringify(hyp.get("claim") or hyp.get("summary") or hypothesis),
            subtitle=_stringify(hyp.get("rationale") or hyp.get("reason")),
            status=_stringify(hyp.get("status")),
            confidence=_stringify(hyp.get("confidence")),
            data={"raw": hyp},
        )
        add_edge(analysis_node, hyp_node, "HAS_HYPOTHESIS", "候选假设")

        for ev_idx, evidence in enumerate(_first_list(hyp, ["supporting_evidence", "evidence", "log_evidence"])[:8], start=1):
            ev_text = _stringify(evidence)
            ev_node = add_node(
                f"evidence:{_safe_key(hyp_id)}:{ev_idx}",
                "evidence",
                f"{hyp_id} 证据 {ev_idx}",
                title=ev_text,
                data={"kind": "supporting"},
            )
            add_edge(hyp_node, ev_node, "SUPPORTED_BY", "支持证据")

        for ev_idx, evidence in enumerate(_first_list(hyp, ["contradicting_evidence", "counter_evidence"])[:6], start=1):
            ev_text = _stringify(evidence)
            ev_node = add_node(
                f"counter_evidence:{_safe_key(hyp_id)}:{ev_idx}",
                "evidence",
                f"{hyp_id} 反证 {ev_idx}",
                title=ev_text,
                data={"kind": "contradicting"},
            )
            add_edge(hyp_node, ev_node, "CONTRADICTED_BY", "反证")

        for ref_idx, code_ref in enumerate(_first_list(hyp, ["code_refs", "code_references", "files", "changed_files"])[:10], start=1):
            ref_text = _stringify(code_ref)
            ref_node = add_node(
                f"code:{_safe_key(ref_text)}",
                "code_ref",
                _clip(ref_text, 72),
                title=ref_text,
            )
            add_edge(hyp_node, ref_node, "TOUCHES_CODE", "关联代码")

        for test_idx, test in enumerate(_first_list(hyp, ["tests_examined", "test_refs", "tests"])[:8], start=1):
            test_text = _stringify(test)
            test_node = add_node(
                f"test:{_safe_key(test_text)}",
                "test",
                _clip(test_text, 72),
                title=test_text,
            )
            add_edge(hyp_node, test_node, "EXAMINES_TEST", "关联测试")

    for idx, review in enumerate(_as_list(ledger.get("candidate_reviews"))[:12], start=1):
        review_dict = _as_dict(review)
        pr = review_dict.get("pr") or review_dict.get("pr_number") or review_dict.get("number") or idx
        review_node = add_node(
            f"candidate_review:{_safe_key(str(pr))}",
            "candidate_review",
            f"候选审查 {pr}",
            title=_stringify(review_dict.get("reason") or review_dict.get("summary") or review),
            status=_stringify(review_dict.get("status") or review_dict.get("decision")),
            confidence=_stringify(review_dict.get("confidence")),
            data={"raw": review_dict},
        )
        add_edge(analysis_node, review_node, "REVIEWS_CANDIDATE", "候选审查")

    if validation:
        validation_node = add_node(
            f"validation:{analysis.id}",
            "validation",
            "独立审计",
            title=_stringify(validation.get("verdict") or validation.get("summary") or validation),
            status=_stringify(validation.get("status") or validation.get("verdict")),
            confidence=_stringify(validation.get("confidence")),
            data=validation,
        )
        add_edge(analysis_node, validation_node, "VALIDATED_BY", "验证/审计")

    tool_counter: Counter[str] = Counter()
    for step in trace:
        step_dict = _as_dict(step)
        for call in _as_list(step_dict.get("tool_calls")):
            call_dict = _as_dict(call)
            tool_name = _stringify(call_dict.get("name") or call_dict.get("tool") or call)
            if tool_name:
                tool_counter[tool_name] += 1
    for tool_name, count in tool_counter.most_common(8):
        tool_node = add_node(
            f"tool:{_safe_key(tool_name)}",
            "tool",
            tool_name,
            subtitle=f"调用 {count} 次",
            data={"calls": count},
        )
        add_edge(analysis_node, tool_node, "USED_TOOL", "使用工具", data={"calls": count})

    return {
        "analysis_id": analysis.id,
        "generated_at": datetime.now(UTC),
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "hypotheses": sum(1 for n in nodes if n["type"] == "hypothesis"),
            "evidence": sum(1 for n in nodes if n["type"] == "evidence"),
            "code_refs": sum(1 for n in nodes if n["type"] == "code_ref"),
            "tools": sum(1 for n in nodes if n["type"] == "tool"),
        },
    }


def summarize_graph_for_agent(graph: dict[str, Any]) -> dict[str, Any]:
    """Return a compact graph memory for verifier/reporter prompts."""
    nodes = _as_list(graph.get("nodes"))
    edges = _as_list(graph.get("edges"))
    by_type = Counter(str(node.get("type")) for node in nodes if isinstance(node, dict))
    weak_hypotheses: list[str] = []
    hypothesis_ids = {
        str(node.get("id")): str(node.get("label") or node.get("id"))
        for node in nodes
        if isinstance(node, dict) and node.get("type") == "hypothesis"
    }
    edge_types_by_source: dict[str, set[str]] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        edge_types_by_source.setdefault(str(edge.get("source")), set()).add(str(edge.get("type")))
    for node_id, label in hypothesis_ids.items():
        edge_types = edge_types_by_source.get(node_id, set())
        missing: list[str] = []
        if "SUPPORTED_BY" not in edge_types:
            missing.append("supporting_evidence")
        if "TOUCHES_CODE" not in edge_types:
            missing.append("code_refs")
        if "EXAMINES_TEST" not in edge_types:
            missing.append("tests_examined")
        if missing:
            weak_hypotheses.append(f"{label} 缺少 {', '.join(missing)}")

    return {
        "stats": graph.get("stats", {}),
        "node_types": dict(by_type),
        "weak_hypotheses": weak_hypotheses[:12],
        "closed_loop_rule": (
            "后续 agent 必须优先补齐 weak_hypotheses 中缺失的日志/代码/测试关系；"
            "不要把无因果链的 PR 放入 hypotheses。"
        ),
    }


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_list(source: dict[str, Any], keys: list[str]) -> list[Any]:
    for key in keys:
        value = source.get(key)
        if isinstance(value, list):
            return value
        if value:
            return [value]
    return []


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        for key in ("text", "message", "summary", "path", "file", "name", "title", "claim"):
            if value.get(key):
                return _stringify(value[key])
    return str(value)


def _clip(value: str | None, limit: int) -> str:
    if not value:
        return ""
    normalized = " ".join(str(value).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)] + "…"


def _safe_key(value: str) -> str:
    safe = []
    for ch in value[:180]:
        safe.append(ch if ch.isalnum() or ch in "._-:#" else "_")
    return "".join(safe) or "unknown"
