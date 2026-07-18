"""Structured evidence pipeline for CI failure analysis."""

from __future__ import annotations

import json
import re
from typing import Any


LEDGER_SCHEMA = {
    "schema_version": 1,
    "failure_facts": [],
    "regression_boundary": {
        "last_good_run_id": None,
        "last_good_time": None,
        "last_good_sha": None,
        "bad_run_id": None,
        "bad_time": None,
        "bad_sha": None,
    },
    "required_regression_candidates": [],
    "candidate_reviews": [],
    "hypotheses": [],
    "stop_reason": "",
}


def extract_json_object(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append(value)
    if not candidates:
        return {}
    for candidate in candidates:
        if "evidence_ledger" in candidate or "hypotheses" in candidate or "verdict" in candidate:
            return candidate
    return max(candidates, key=lambda item: len(json.dumps(item, ensure_ascii=False)))


def normalize_ledger(raw: dict[str, Any]) -> dict[str, Any]:
    ledger = dict(LEDGER_SCHEMA)
    source = raw.get("evidence_ledger", raw) if isinstance(raw, dict) else {}
    ledger["failure_facts"] = source.get("failure_facts", []) if isinstance(source.get("failure_facts"), list) else []
    boundary = source.get("regression_boundary", {})
    ledger["regression_boundary"] = {**LEDGER_SCHEMA["regression_boundary"], **(boundary if isinstance(boundary, dict) else {})}
    ledger["required_regression_candidates"] = (
        source.get("required_regression_candidates", [])
        if isinstance(source.get("required_regression_candidates"), list)
        else []
    )
    ledger["candidate_reviews"] = (
        source.get("candidate_reviews", [])
        if isinstance(source.get("candidate_reviews"), list)
        else []
    )
    ledger["stop_reason"] = str(source.get("stop_reason", ""))[:1000]
    hypotheses = []
    for index, item in enumerate(source.get("hypotheses", []) if isinstance(source.get("hypotheses"), list) else []):
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "candidate")).lower()
        if status not in {"candidate", "rejected", "confirmed"}:
            status = "candidate"
        hypotheses.append({
            "id": str(item.get("id") or f"H{index + 1}"),
            "claim": str(item.get("claim", ""))[:2000],
            "status": status,
            "confidence": str(item.get("confidence", "low")).lower(),
            "supporting_evidence": _list(item.get("supporting_evidence")),
            "contradicting_evidence": _list(item.get("contradicting_evidence")),
            "code_refs": _list(item.get("code_refs")),
            "tests_examined": _list(item.get("tests_examined")),
            "runtime_path_evidence": _list(item.get("runtime_path_evidence")),
            "calculations": _list(item.get("calculations")),
            "evidence_gaps": _list(item.get("evidence_gaps")),
            "verification_actions": _list(item.get("verification_actions")),
        })
    ledger["hypotheses"] = hypotheses
    return ledger


def enrich_ledger_from_trace(ledger: dict[str, Any], trace: list[dict[str, Any]]) -> dict[str, Any]:
    """Add deterministic facts found in tool observations.

    The investigator LLM can occasionally observe a key log line but omit it
    from the final evidence ledger.  Keep this enrichment narrow and factual:
    it must only add facts that are literally present in tool observations.
    """
    facts = list(ledger.get("failure_facts") or [])
    joined_observations = "\n".join(
        str(entry.get("observation") or "") for entry in trace if isinstance(entry, dict)
    )

    def add_fact(text: str) -> None:
        if text and text not in facts:
            facts.append(text)

    if "Accuracy verification failed" in joined_observations:
        add_fact("Log shows accuracy benchmark failed: Accuracy verification failed.")

    textvqa_match = re.search(
        r"(?:textvqa[^\n]{0,120}?accuracy[^\n]{0,120}?|accuracy[^\n]{0,120}?textvqa[^\n]{0,120}?)(57\.\d+)",
        joined_observations,
        flags=re.IGNORECASE,
    )
    if textvqa_match:
        add_fact(f"Log records TextVQA accuracy around {textvqa_match.group(1)}.")

    threshold_match = re.search(
        r"(?:threshold|baseline|expected|target|goal)[^\n]{0,80}(8[0-9](?:\.\d+)?)",
        joined_observations,
        flags=re.IGNORECASE,
    )
    if threshold_match:
        add_fact(f"Log/report context mentions an accuracy threshold or baseline around {threshold_match.group(1)}.")

    if "Using default backend AttentionBackendEnum.TORCH_SDPA for vit attention" in joined_observations:
        add_fact("Log shows ViT attention backend is AttentionBackendEnum.TORCH_SDPA.")
    if "Using AttentionBackendEnum.TORCH_SDPA for MMEncoderAttention" in joined_observations:
        add_fact("Log shows MMEncoderAttention backend is AttentionBackendEnum.TORCH_SDPA; this is a backend-selection fact, not a standalone proof that wrappers, argument construction, or pre/post-processing code did not run.")
    if "EADDRINUSE" in joined_observations or "address already in use" in joined_observations.lower():
        add_fact("Log shows distributed initialization failed with EADDRINUSE/address already in use.")
    if "WorkerProc failed to start" in joined_observations:
        add_fact("Log shows one or more vLLM WorkerProc instances failed to start.")
    dist_match = re.search(
        r"distributed_init_method=tcp://([0-9.]+):(\d+)[^\n]{0,160}backend=([a-z0-9_]+)",
        joined_observations,
        flags=re.IGNORECASE,
    )
    if dist_match:
        add_fact(
            "Log records distributed init endpoint "
            f"tcp://{dist_match.group(1)}:{dist_match.group(2)} backend={dist_match.group(3)}."
        )
    timeout_match = re.search(
        r"Timeout:[^\n]{0,120}nodes did not become ready:[^\n]{0,120}",
        joined_observations,
        flags=re.IGNORECASE,
    )
    if timeout_match:
        add_fact(f"Log shows readiness timeout: {timeout_match.group(0)[:220]}.")

    ledger["failure_facts"] = facts
    _enrich_regression_boundary_from_trace(ledger, trace)
    _enrich_hypotheses_from_trace(ledger, trace)
    _soften_backend_only_rejections(ledger)
    return ledger


def extract_required_regression_candidates(text: str) -> list[dict[str, Any]]:
    """Extract the deterministic candidate coverage list from job context."""
    if "required_regression_candidates" not in text:
        return []
    candidates: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    for marker in re.finditer(r"\"required_regression_candidates\"", text):
        start = text.rfind("{", 0, marker.start())
        if start < 0:
            continue
        try:
            data, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        value = data.get("required_regression_candidates")
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            sha = str(item.get("sha") or "")
            if not re.fullmatch(r"[0-9a-f]{7,40}", sha, flags=re.IGNORECASE):
                continue
            candidates.append({
                "sha": sha,
                "pr": str(item.get("pr") or ""),
                "title": str(item.get("title") or "")[:300],
                "score": int(item.get("score") or 0),
                "matched_keywords": _list(item.get("matched_keywords"))[:12],
            })
    # De-duplicate by short SHA/PR while preserving order.
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for item in candidates:
        key = (item["sha"][:7].lower(), item.get("pr", ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:20]


def _trace_text(trace: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for entry in trace:
        if not isinstance(entry, dict):
            continue
        phase = str(entry.get("phase") or "")
        model_output = str(entry.get("model_output") or "")
        observation = str(entry.get("observation") or "")
        if phase:
            parts.append(f"[phase={phase}]")
        if model_output:
            parts.append(model_output)
        if observation:
            parts.append(observation)
    return "\n".join(parts)


def _enrich_regression_boundary_from_trace(ledger: dict[str, Any], trace: list[dict[str, Any]]) -> None:
    """Backfill bad/last-good SHAs that were explicitly observed in trace."""
    boundary = dict(LEDGER_SCHEMA["regression_boundary"])
    boundary.update(ledger.get("regression_boundary") or {})
    text = _trace_text(trace)

    if not boundary.get("bad_sha"):
        match = re.search(r"\bvllm_ascend_ref:\s*([0-9a-f]{7,40})\b", text, re.IGNORECASE)
        if match:
            boundary["bad_sha"] = match.group(1)
    if not boundary.get("bad_run_id"):
        match = re.search(r"\brun[_ #:-]*(\d{8,})\b", text, re.IGNORECASE)
        if match:
            boundary["bad_run_id"] = match.group(1)
    if not boundary.get("last_good_sha"):
        last_good_matches = list(
            re.finditer(r"(?:last[- ]?good|上次成功|成功运行)[^\n]{0,180}\b([0-9a-f]{7,40})\b", text, re.IGNORECASE)
        )
        for match in reversed(last_good_matches):
            context = text[max(0, match.start() - 80): min(len(text), match.end() + 120)]
            if any(marker in context for marker in ("未记录", "失败", "failed", "not recorded")):
                continue
            boundary["last_good_sha"] = match.group(1)
            break
        if not boundary.get("last_good_sha"):
            match = re.search(r"base_ref['\"]?\s*[:=]\s*['\"]([0-9a-f]{7,40})['\"]", text, re.IGNORECASE)
            if match:
                boundary["last_good_sha"] = match.group(1)
    if not boundary.get("bad_sha"):
        match = re.search(r"head_ref['\"]?\s*[:=]\s*['\"]([0-9a-f]{7,40})['\"]", text, re.IGNORECASE)
        if match:
            boundary["bad_sha"] = match.group(1)

    ledger["regression_boundary"] = boundary


def _enrich_hypotheses_from_trace(ledger: dict[str, Any], trace: list[dict[str, Any]]) -> None:
    """Recover explicit commit/PR hypotheses from investigation trace."""
    hypotheses = list(ledger.get("hypotheses") or [])
    existing_text = "\n".join(str(h.get("claim", "")) for h in hypotheses)
    text = _trace_text(trace)
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    positive_markers = (
        "强有力", "强候选", "有希望", "关键嫌疑", "真正的罪魁祸首", "进一步证实",
        "决定性证据", "直接影响", "最可疑", "非常可疑", "高度相关",
        "首选嫌疑", "主要的候选", "主要候选", "候选点", "有趣的候选", "罪魁祸首",
        "root cause", "culprit", "strong candidate",
    )
    negative_markers = ("无关", "不会被触发", "不使用", "干扰项", "排除", "not triggered", "irrelevant")

    pair_sources: list[tuple[str, str, int, str]] = [
        (sha, pr, position, "prose") for sha, pr, position in _commit_pr_pairs(text)
    ]
    pair_sources.extend(_tool_commit_refs(trace, text))
    seen_candidate_keys: set[tuple[str, str]] = set()
    for order, (sha, pr, position, source) in enumerate(pair_sources):
        candidate_key = (sha[:7].lower(), pr)
        if candidate_key in seen_candidate_keys:
            continue
        start = max(0, position - 700)
        end = min(len(text), position + 900)
        context = text[start:end]
        local_context = text[max(0, position - 350): min(len(text), position + 350)]
        if _is_negated_pr_context(local_context, pr):
            continue
        if f"#{pr}" in existing_text or sha[:7] in existing_text:
            continue
        score = sum(1 for marker in positive_markers if marker.lower() in local_context.lower())
        if score == 0:
            continue
        confidence = "high" if score >= 2 else ("medium" if score == 1 else "low")
        if any(marker.lower() in local_context.lower() for marker in negative_markers) and score < 2:
            confidence = "low"
        seen_candidate_keys.add(candidate_key)
        candidate = {
            "id": f"H{len(hypotheses) + len(candidates) + 1}",
            "claim": f"commit {sha[:7]} / PR #{pr} 是本次失败的主要候选根因，需要结合日志与代码路径审计。",
            "status": "candidate",
            "confidence": confidence,
            "supporting_evidence": [_clip(context, 900)],
            "contradicting_evidence": [],
            "code_refs": _extract_code_refs_near(context),
            "tests_examined": [],
            "runtime_path_evidence": [],
            "calculations": [],
            "evidence_gaps": [
                "该候选由 agent trace 回填：调查过程已检查该 commit，但最终 evidence_ledger 遗漏；需要 verifier 继续审计其调用链、回归边界和日志证据。"
            ],
            "verification_actions": [
                "检查该 commit 的 diff、相关运行日志、artifact 详细日志以及 last-good/bad 边界。"
            ],
        }
        candidates.append((score, order, candidate))

    if candidates:
        candidates.sort(key=lambda item: (-item[0], item[1]))
        hypotheses.extend(item[2] for item in candidates[:5])
        ledger["hypotheses"] = hypotheses


def _is_negated_pr_context(context: str, pr: str) -> bool:
    """Return True when nearby prose explicitly says this PR is not the cause.

    This is deliberately PR-agnostic: it never names a concrete PR number.
    It only checks whether negation terms syntactically occur near the current
    candidate PR reference.
    """
    escaped_pr = re.escape(str(pr))
    patterns = [
        rf"(?:不是|并非|不是由|并不是|排除|排除了|不太可能|不像是|rather than|not|unlikely)[^\n。；;]{{0,40}}(?:PR\s*)?#\s*{escaped_pr}\b",
        rf"(?:PR\s*)?#\s*{escaped_pr}\b[^\n。；;]{{0,40}}(?:不是|并非|被排除|不太可能|unlikely|not the cause)",
    ]
    return any(re.search(pattern, context, flags=re.IGNORECASE) for pattern in patterns)


def _tool_commit_refs(trace: list[dict[str, Any]], full_text: str) -> list[tuple[str, str, int, str]]:
    """Recover commit/PR candidates from tool calls and nearby observations.

    The final investigator JSON is sometimes too terse, while the trace already
    contains strong commit investigation steps.  Tool arguments give a reliable
    SHA; nearby commit-show output or prose often gives the PR number.
    """
    refs: list[tuple[str, str, int, str]] = []
    seen: set[tuple[str, str]] = set()
    cursor = 0

    def add(sha: str, pr: str, position: int) -> None:
        key = (sha[:7].lower(), pr)
        if key in seen:
            return
        seen.add(key)
        refs.append((sha, pr, position, "tool"))

    for entry in trace:
        if not isinstance(entry, dict):
            continue
        entry_text = "\n".join(
            str(entry.get(key) or "") for key in ("model_output", "observation")
        )
        position = full_text.find(entry_text[:80], cursor) if entry_text else -1
        if position < 0:
            position = cursor
        cursor = max(cursor, position + len(entry_text))

        shas: list[str] = []
        for call in entry.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            function = call.get("function") if isinstance(call.get("function"), dict) else {}
            if function.get("name") != "git_show_commit":
                continue
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            if isinstance(arguments, dict):
                sha = str(arguments.get("commit_ref") or "")
                if re.fullmatch(r"[0-9a-f]{7,40}", sha, flags=re.IGNORECASE):
                    shas.append(sha)

        if not shas:
            continue
        prs = re.findall(r"(?:PR\s*)?#(\d{4,6})", entry_text, flags=re.IGNORECASE)
        title_pairs = _commit_pr_pairs(entry_text)
        for sha, pr, local_position in title_pairs:
            add(sha, pr, position + local_position)
        if len(shas) == 1 and prs:
            add(shas[0], prs[0], position)

    return refs


def _commit_pr_pairs(text: str) -> list[tuple[str, str, int]]:
    pairs: list[tuple[str, str, int]] = []
    seen: set[tuple[str, str]] = set()

    def add(sha: str, pr: str, position: int) -> None:
        key = (sha[:7].lower(), pr)
        if key in seen:
            return
        seen.add(key)
        pairs.append((sha, pr, position))

    # Investigator prose: "`<sha>` - ... (#<pr>)" or "(PR #<pr>)".
    inline_re = re.compile(
        r"(?:`(?P<sha_bt>[0-9a-f]{7,40})`|commit\s+(?P<sha_word>[0-9a-f]{7,40}))[^\n]{0,220}?(?:PR\s*)?#(?P<pr>\d{4,6})",
        re.IGNORECASE,
    )
    for match in inline_re.finditer(text):
        add(match.group("sha_bt") or match.group("sha_word"), match.group("pr"), match.start())

    # Chinese/prose title form: "<sha> - ... (#<pr>)".
    title_re = re.compile(
        r"`?(?P<sha>[0-9a-f]{7,40})`?\s*[-:：]\s*[^\n]{0,260}?\(#(?P<pr>\d{4,6})\)",
        re.IGNORECASE,
    )
    for match in title_re.finditer(text):
        add(match.group("sha"), match.group("pr"), match.start())

    # Commit show output: "commit <sha>" followed shortly by title "(#12345)".
    commit_show_re = re.compile(
        r"commit\s+(?P<sha>[0-9a-f]{7,40})[^\n]*(?:\n[^\n]*){0,12}?\(#(?P<pr>\d{4,6})\)",
        re.IGNORECASE,
    )
    for match in commit_show_re.finditer(text):
        add(match.group("sha"), match.group("pr"), match.start())

    return pairs


def _clip(text: str, limit: int) -> str:
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _extract_code_refs_near(text: str) -> list[str]:
    refs = sorted(set(re.findall(r"\b[\w./-]+\.(?:py|yaml|yml|cpp|h|md)\b", text)))
    return refs[:8]


def _soften_backend_only_rejections(ledger: dict[str, Any]) -> None:
    """General evidence gate: a single runtime label cannot reject a code hypothesis.

    Runtime labels such as backend/mode/device/runner/framework are useful clues,
    but they are not a reachability proof.  A hypothesis may be rejected only
    when the evidence contains a concrete unreachable or mutually-exclusive path
    proof, or when the commit is outside the regression boundary.
    """
    weak_label_markers = (
        "backend",
        "mode",
        "device",
        "runner",
        "framework",
        "TORCH_SDPA",
        "FIA",
        "ACL",
        "environment",
        "label",
        "后端",
        "模式",
        "设备",
        "环境",
        "标签",
    )
    strong_rejection_markers = (
        "call graph proves",
        "caller proof",
        "unreachable",
        "dead code",
        "cannot execute",
        "mutually exclusive",
        "disabled by config",
        "outside regression range",
        "not in regression range",
        "调用链证明",
        "不可达",
        "无调用方",
        "互斥",
        "配置关闭",
        "不在回归区间",
    )
    neutral_fact = (
        "运行时标签（如 backend/mode/device/runner/framework）只能作为线索；"
        "若要排除代码假设，必须补充调用链不可达、配置互斥、提交不在回归区间等强反证。"
    )
    facts = list(ledger.get("failure_facts", []) or [])
    if any(any(marker in str(fact) for marker in weak_label_markers) for fact in facts):
        if neutral_fact not in facts:
            facts.append(neutral_fact)
    ledger["failure_facts"] = facts

    for hypothesis in ledger.get("hypotheses", []):
        if hypothesis.get("status") != "rejected":
            continue
        contradictions = [str(item) for item in hypothesis.get("contradicting_evidence", [])]
        if not contradictions:
            continue
        has_label_evidence = any(
            any(marker in item for marker in weak_label_markers)
            for item in contradictions
        )
        has_strong_rejection = any(
            any(marker in item for marker in strong_rejection_markers)
            for item in contradictions
        )
        if has_label_evidence and not has_strong_rejection:
            hypothesis["status"] = "candidate"
            hypothesis["confidence"] = str(hypothesis.get("confidence") or "medium")
            gaps = hypothesis.setdefault("evidence_gaps", [])
            gaps.append(
                "该假设曾被运行时标签类证据排除，但缺少调用链不可达/配置互斥/回归区间外等强反证；已恢复为候选并要求继续做日志↔代码仓往返验证。"
            )
            runtime = hypothesis.setdefault("runtime_path_evidence", [])
            runtime.append(
                "当前仅有运行时标签类证据；它不足以单独排除相关代码路径，需要结合源码入口、调用方、配置选择和 artifact 日志确认。"
            )


def _rejection_has_source_call_chain_proof(hypothesis: dict[str, Any]) -> bool:
    """Return whether a rejected hypothesis contains concrete source reachability proof."""
    combined = "\n".join(
        json.dumps(hypothesis.get(key, []), ensure_ascii=False)
        for key in ("code_refs", "contradicting_evidence", "runtime_path_evidence", "calculations")
    )
    has_source_ref = bool(re.search(r"\b[\w./-]+\.py\b", combined)) and bool(
        re.search(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", combined)
    )
    has_call_chain_marker = any(marker in combined for marker in (
        "调用链",
        "调用方",
        "不可达",
        "未调用",
        "不经过",
        "源码证明",
        "配置互斥",
        "disabled by config",
        "call graph",
        "caller",
        "unreachable",
        "not called",
        "does not call",
        "does not pass through",
        "mutually exclusive",
    ))
    # Pure runtime labels are not source proof by themselves.
    weak_label_only = any(marker in combined for marker in (
        "TORCH_SDPA", "FIA", "ACL", "backend", "后端", "runner", "device", "环境"
    )) and not has_source_ref
    return has_source_ref and has_call_chain_marker and not weak_label_only


def normalize_auditor_validation(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a schema-safe verifier result.

    If the verifier returns a tool-call JSON or malformed content, keep the
    failure explicit instead of storing that object as the auditor verdict.
    """
    allowed = {"pass", "likely", "revise", "insufficient"}
    if not isinstance(raw, dict):
        return {"verdict": "insufficient", "findings": ["verifier returned non-object content"]}
    verdict = str(raw.get("verdict", "")).lower()
    if verdict not in allowed:
        return {
            "verdict": "insufficient",
            "findings": ["verifier did not return a valid audit verdict"],
            "parse_error": True,
            "raw_keys": sorted(str(key) for key in raw.keys()),
        }
    return raw


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else ([] if value in (None, "") else [value])


def programmatic_validate(
    ledger: dict[str, Any],
    required_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    boundary = ledger.get("regression_boundary", {})
    if required_candidates is not None:
        ledger["required_regression_candidates"] = required_candidates
    required_candidates = list(
        required_candidates
        if required_candidates is not None
        else ledger.get("required_regression_candidates", []) or []
    )
    if not boundary.get("last_good_sha") or not boundary.get("bad_sha"):
        findings.append({"severity": "error", "code": "missing_regression_boundary", "message": "last-good and bad SHA are required"})
    if not ledger.get("failure_facts"):
        findings.append({"severity": "error", "code": "missing_failure_facts", "message": "no primary log facts recorded"})
    if not ledger.get("hypotheses"):
        findings.append({"severity": "error", "code": "missing_hypotheses", "message": "no code hypotheses recorded"})

    for hypothesis in ledger.get("hypotheses", []):
        hid = hypothesis.get("id", "unknown")
        if not hypothesis.get("supporting_evidence"):
            findings.append({"severity": "error", "code": "unsupported_hypothesis", "message": f"{hid} has no supporting evidence"})
        if hypothesis.get("code_refs") and not hypothesis.get("tests_examined"):
            findings.append({"severity": "warning", "code": "tests_not_examined", "message": f"{hid} cites code changes but no changed tests"})
        if hypothesis.get("status") == "rejected" and not _rejection_has_source_call_chain_proof(hypothesis):
            hypothesis["status"] = "candidate"
            hypothesis["confidence"] = "low"
            gaps = hypothesis.setdefault("evidence_gaps", [])
            gaps.append(
                "该假设曾被标记为 rejected，但缺少可审计的源码调用链/配置互斥证明；已降级为 candidate。"
            )
            findings.append({
                "severity": "error",
                "code": "rejection_without_source_call_chain",
                "message": f"{hid} was rejected without auditable source call-chain or config-mutual-exclusion proof",
            })
        if hypothesis.get("status") == "confirmed" and (
            hypothesis.get("evidence_gaps")
            or not hypothesis.get("runtime_path_evidence")
            or hypothesis.get("contradicting_evidence")
        ):
            hypothesis["status"] = "candidate"
            hypothesis["confidence"] = "medium" if hypothesis.get("runtime_path_evidence") else "low"
            findings.append({"severity": "error", "code": "confirmation_downgraded", "message": f"{hid} was confirmed without closed evidence and was downgraded"})

    verdict = "pass"
    if any(item["severity"] == "error" for item in findings):
        verdict = "insufficient"
    return {"verdict": verdict, "findings": findings, "ledger": ledger}


def investigation_prompt(job_context: str) -> str:
    return f"""请使用可用的日志和代码仓工具调查此 CI 失败。分析过程和 JSON 中的自然语言说明使用简体中文；代码、路径、SHA、命令和日志原文保持原样。不要撰写面向用户的报告。最终答案只能是一个名为 evidence_ledger 的 JSON 对象。

必须维护相互竞争的假设，同时记录支持证据和反证。代码假设必须检查并记录相关变更测试。只有存在直接运行路径证据、没有未解决的因果缺口、且没有强反证时，才能将 status 标记为 confirmed。如果无法重跑 runner 或大模型准确率测试，不要因此单独降级；请把它记录为 verification_actions。

关键调查要求：
- 从失败 Job 的完整 job log 和 GitHub steps_data 中标记为 failure/timed_out/startup_failure 的步骤开始，定位失败事实、执行配置、bad commit/SHA、run_id、时间；不要假设失败步骤一定叫 stream log，实际名称可能是 Run Pytest (xxx)、Run Test、Upload/Check 等。
- 找到上一次同一 workflow/job/config 的成功运行，记录 last-good run_id/time/SHA。
- 在 bad 与 last-good 之间查看 commit/PR 列表，但不要把区间内所有提交都当作候选；commit/PR 列表只是调查材料。
- 先从失败日志归纳失败机制，再到代码仓追踪“日志症状 → 运行入口/配置 → 可能受影响源码路径 → 区间提交 diff”的因果链。只有这条链能连上时，才把提交提升为候选假设。
- 对每个被提升的候选，必须在日志、artifact 详细日志和代码仓之间来回验证：看 diff、看调用链、看配置是否启用、看日志是否出现相关路径。
- 若要把候选标记为 rejected，必须在 code_refs / contradicting_evidence / runtime_path_evidence 中写出可审计的源码调用链证明：从本 Job 实际入口/配置选择到候选修改函数为什么不可达，或哪个配置分支与候选路径互斥。单一运行时标签（backend、mode、device、runner、framework、TORCH_SDPA、FIA、ACL 等）只能作为线索，不能单独排除代码假设。
- 如果 artifact 已下载或已解压，必须优先查看和列出其中与当前 job 对应的详细日志目录，不要误报“未解压详细日志”。
Required shape:
{json.dumps(LEDGER_SCHEMA, ensure_ascii=False)}

Each hypothesis must contain: id, claim, status, confidence, supporting_evidence, contradicting_evidence,
code_refs, tests_examined, runtime_path_evidence, calculations, evidence_gaps, verification_actions.
如果 JOB CONTEXT 中包含 required_regression_candidates，把它们仅视为“回归区间审查线索”，不是必须覆盖清单，更不是候选根因清单。
处理方式：
- 不需要逐一解释 good..bad 区间内的所有提交。
- 不能仅靠标题关键词、文件名关键词、模型名或 PR 标签判断相关性。
- 只有存在日志事实、源码调用链、配置入口、测试影响或运行路径证据时，才放入 hypotheses，状态为 confirmed/candidate/rejected。
- 如果只是关键词命中但没有因果链，不要放入 hypotheses；只有当它会帮助解释调查路径时，才可放入 candidate_reviews，并记录 disposition=dismissed/not_candidate/no_runtime_relevance。
- 若 rejected，必须给出源码调用链不可达、配置互斥、提交不在目标 ref 等强反证，不能静默遗漏，也不能只用 backend 标签排除。

JOB CONTEXT:
{job_context}
"""


def verification_prompt(ledger: dict[str, Any], graph_summary: dict[str, Any] | None = None) -> str:
    return f"""你是独立的 CI 证据审计员。可以使用受控工具重新检查关键日志、artifact 文件列表和 git 代码/commit 证据，但不要重新完整调查，不要使用 shell。JSON 中的自然语言说明使用简体中文。

对每个代码假设，检查候选提交修改的测试、提交意图、调用方、失败日志事实、last-good/bad 边界，以及该 Job 对应的具体计算过程。
如果 ledger 中包含 required_regression_candidates，只把它们当作审查线索。不要要求全部覆盖，也不要因为未逐一解释区间提交而返回 revise/insufficient。重点审计：进入 hypotheses 的候选是否真的有“日志症状 → 运行入口/配置 → 源码路径 → diff”的因果链；无此链路的条目必须降级或移出候选。
对任何 status=rejected 的假设，必须复核其源码调用链证明是否可审计：如果只是引用 TORCH_SDPA/FIA/ACL/backend/runner 等运行时标签，或没有从入口函数到候选函数的不可达/互斥源码证据，必须返回 revise/insufficient，并要求降级为 candidate。
只返回 JSON，字段为：verdict (pass|likely|revise|insufficient)、hypothesis_reviews、findings、approved_claims、rejected_claims、required_changes、report_constraints。

判定标准：
- pass：离线证据链闭合，且日志/代码/调用链/边界均支持，可作为确认根因。
- likely：无法重跑，但离线取证已形成一致证据链；可作为主要嫌疑/高置信候选输出，注明待运行复现。
- insufficient：缺 last-good/bad、缺主要失败事实、代码假设没有测试/调用链检查、存在强反证，或关键因果环节缺失。
- revise：需要调查员修正事实或补充明显遗漏。

重要语义：regression_boundary.bad_sha 表示失败运行 checkout 的 HEAD，不等于“引入回归的提交”。如果 bad_sha 是纯文档提交，只能说明根因需要在 last_good_sha..bad_sha 区间内继续查找，不能据此判定整个分析无效。

不要因为无法登录 runner、无法复跑 benchmark、无法再次执行大模型准确率测试，就把 otherwise 一致的离线证据链降为 insufficient。不能仅仅因为后续存在 revert 就把候选假设提升为 confirmed/pass。单一运行时标签不能作为排除候选的充分依据。
LEDGER:
{json.dumps(ledger, ensure_ascii=False)}

KNOWLEDGE GRAPH MEMORY:
{json.dumps(graph_summary or {}, ensure_ascii=False)}
"""


def revision_prompt(
    job_context: str,
    ledger: dict[str, Any],
    graph_summary: dict[str, Any],
    auditor_validation: dict[str, Any],
) -> str:
    return f"""你是 CI 失败分析调查员，正在根据 verifier 的审计意见做一次定向补证。只允许输出修正后的 evidence_ledger JSON，不要写报告。

闭环目标：
- 优先处理 KNOWLEDGE GRAPH MEMORY 中的 weak_hypotheses。
- 对 verifier.required_changes 指出的缺口，回到日志和代码仓补证。
- 如果某个 PR/commit 没有“日志症状 → 运行入口/配置 → 源码路径 → diff”链路，应从 hypotheses 移出，必要时放入 candidate_reviews 且 disposition=dismissed/not_candidate/no_runtime_relevance。
- 若要 rejected，必须给出源码调用链不可达或配置互斥证据，不能只用 backend/runner/TORCH_SDPA/FIA/ACL 等标签。
- 如果无法重跑 runner/benchmark，把它写入 verification_actions，不要因此单独降级为证据不足。

CURRENT LEDGER:
{json.dumps(ledger, ensure_ascii=False)}

KNOWLEDGE GRAPH MEMORY:
{json.dumps(graph_summary, ensure_ascii=False)}

VERIFIER AUDIT:
{json.dumps(auditor_validation, ensure_ascii=False)}

JOB CONTEXT:
{job_context}
"""


def report_prompt(
    ledger: dict[str, Any],
    validation: dict[str, Any],
    graph_summary: dict[str, Any] | None = None,
) -> str:
    return f"""请根据下方证据，用简体中文撰写最终 CI 失败分析报告。你没有代码仓工具，不得增加任何新事实。

报告标题、章节、解释、结论、表格内容、根因摘要和改进建议必须使用简体中文；代码符号、文件路径、commit SHA、PR 编号、命令和原始日志引用保持原文，不要翻译或改写。必须清晰区分：观察到的失败、已确认事实、主要嫌疑、其他候选、已审查但未成为候选的提交、已排除假设、证据缺口和后续验证方法。

结论措辞规则：
- validation.verdict == pass：可以使用“确认根因”。
- validation.verdict == likely：使用“主要嫌疑 / 高置信候选 / 离线取证充分，待运行复现”，不要反复写“未验证”。
- validation.verdict == insufficient：使用“候选 / 证据不足”，不得使用确定性根因措辞。

最后输出 JSON，包含 problem_category、root_cause_summary、improvement_measures_summary；三个字段的值也必须使用简体中文，并遵守上面的结论措辞规则。
required_regression_candidates 只是回归区间审查线索，不是覆盖清单，也不是候选根因清单。不能仅靠关键词、标题、文件名或 PR 标签把提交写成候选。只有 ledger.hypotheses 中且存在“日志症状 → 运行入口/配置 → 源码路径 → diff”支持证据的条目才能写入“主要嫌疑/其他候选”；ledger.candidate_reviews 中 disposition 为 dismissed/not_candidate/no_runtime_relevance 的条目只能写入“已审查但未成为候选”，不能称为候选根因。
EVIDENCE LEDGER:
{json.dumps(ledger, ensure_ascii=False)}

VALIDATION:
{json.dumps(validation, ensure_ascii=False)}

KNOWLEDGE GRAPH MEMORY:
{json.dumps(graph_summary or {}, ensure_ascii=False)}
"""


def enforce_validation_on_report(report: str, validation: dict[str, Any]) -> str:
    """Deterministically keep report wording aligned with evidence strength."""
    verdict = str(validation.get("verdict", "insufficient")).lower()
    if verdict == "pass":
        return report
    if verdict in {"likely", "probable"}:
        return _enforce_likely_report(report)
    return _enforce_insufficient_report(report, validation)


def _enforce_likely_report(report: str) -> str:
    safe_report = report
    summary = _extract_complete_report_json(safe_report)
    if summary:
        root = str(summary.get("root_cause_summary", "")).strip()
        if not _has_likely_marker(root):
            root = f"主要嫌疑（离线取证充分，待运行复现）：{root}"
        summary["root_cause_summary"] = root
        start, end = _complete_report_json_span(safe_report)
        if start is not None:
            safe_report = safe_report[:start] + json.dumps(summary, ensure_ascii=False, indent=2) + safe_report[end:]
    gate = (
        "## 离线取证结论\n\n"
        "> **主要嫌疑已形成一致证据链。** 当前结论基于失败日志、历史成功边界、代码 diff、调用链和测试覆盖的离线取证；"
        "由于无法重跑 runner 或复现大模型准确率测试，仍标注为待运行复现，而不是证据不足。\n\n"
    )
    return gate + safe_report


def _enforce_insufficient_report(report: str, validation: dict[str, Any]) -> str:
    auditor = validation.get("auditor")
    auditor = auditor if isinstance(auditor, dict) else {}
    counterevidence = _string_items(auditor.get("rejected_claims") or auditor.get("findings"))
    required = _string_items(auditor.get("required_changes") or auditor.get("report_constraints"))
    safe_report = report
    summary = _extract_complete_report_json(safe_report)
    if summary:
        root = str(summary.get("root_cause_summary", "")).strip()
        if not root.startswith("候选（证据不足）"):
            root = f"候选（证据不足）：{root}"
        if counterevidence:
            root += "；关键反证：" + "；".join(counterevidence[:3])
        summary["root_cause_summary"] = root
        start, end = _complete_report_json_span(safe_report)
        if start is not None:
            safe_report = safe_report[:start] + json.dumps(summary, ensure_ascii=False, indent=2) + safe_report[end:]
    gate_lines = [
        "## 证据门禁结论",
        "",
        "> **证据不足，不能确认主要嫌疑。** 下文涉及的提交和代码路径只能作为候选，不能作为确定性归因。",
    ]
    if counterevidence:
        gate_lines.extend(["", "关键反证："] + [f"- {item}" for item in counterevidence[:5]])
    if required:
        gate_lines.extend(["", "确认主要嫌疑前必须补充："] + [f"- {item}" for item in required[:5]])
    return "\n".join(gate_lines) + "\n\n" + safe_report


def _has_likely_marker(text: str) -> bool:
    markers = ("主要嫌疑", "高置信候选", "离线取证充分", "待运行复现", "likely", "probable")
    lower = text.lower()
    return any(marker.lower() in lower for marker in markers)


def _string_items(value: Any) -> list[str]:
    values = value if isinstance(value, list) else ([] if value in (None, "") else [value])
    result: list[str] = []
    for item in values:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = str(item.get("message") or item.get("claim") or json.dumps(item, ensure_ascii=False)).strip()
        else:
            text = str(item).strip()
        if text:
            result.append(text[:1000])
    return result


def _complete_report_json_span(text: str) -> tuple[int | None, int | None]:
    decoder = json.JSONDecoder()
    required = {"problem_category", "root_cause_summary", "improvement_measures_summary"}
    matches: list[tuple[int, int]] = []
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, consumed = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and required.issubset(value):
            matches.append((start, start + consumed))
    return matches[-1] if matches else (None, None)


def _extract_complete_report_json(text: str) -> dict[str, Any]:
    start, end = _complete_report_json_span(text)
    if start is None:
        return {}
    try:
        value = json.loads(text[start:end])
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}
