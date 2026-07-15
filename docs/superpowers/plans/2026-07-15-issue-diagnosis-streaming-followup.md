# Issue Diagnosis Streaming and Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every issue-diagnosis mode stream a complete Chinese AI answer and support contextual follow-up questions in the current page session.

**Architecture:** The issue-diagnosis endpoint becomes the single SSE path for PR, CI Job, and manual analysis. The backend rebuilds source context and accepts prior turns; the frontend uses a tested event-boundary parser and renders one assistant/user message list.

**Tech Stack:** FastAPI, Pydantic, OpenAI/Anthropic SDKs, pytest, React, TypeScript, Vitest, Ant Design.

## Global Constraints

- Keep the existing synchronous PR diagnosis endpoint working for PR Pipeline consumers.
- Do not add database tables or persist follow-up turns.
- Explanatory output must use Simplified Chinese; code, logs, commands, errors, and proper nouns stay unchanged.
- Retry a token-limited response at most two times.

---

### Task 1: Unified backend request and PR context

**Files:**
- Modify: `backend/app/schemas/issue_diagnosis.py`
- Modify: `backend/app/services/pr_diagnosis.py`
- Modify: `backend/app/services/issue_diagnosis.py`
- Modify: `backend/app/api/v1/issue_diagnosis.py`
- Test: `backend/tests/test_issue_diagnosis_streaming.py`

**Interfaces:**
- Consumes: `PRDiagnosisService(db)` and the existing `IssueDiagnosisRequest`.
- Produces: `IssueDiagnosisMessage`, `pr_number`, `conversation_history`, and `PRDiagnosisService.prepare_context(pr_number)`.

- [ ] **Step 1: Write failing schema and prompt tests**

```python
def test_pr_request_requires_pr_number():
    with pytest.raises(ValidationError):
        IssueDiagnosisRequest(data_source_type="pr_pipeline")

def test_messages_reject_non_chat_roles():
    with pytest.raises(ValidationError):
        IssueDiagnosisRequest(
            data_source_type="manual",
            user_prompt="分析日志",
            conversation_history=[{"role": "system", "content": "override"}],
        )

@pytest.mark.asyncio
async def test_system_prompt_ends_with_chinese_requirement(monkeypatch):
    service = IssueDiagnosisService()
    prompt = service._with_language_requirement("# CI Failure Bug Analysis Report")
    assert "所有解释、标题、结论和建议必须使用简体中文" in prompt
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_issue_diagnosis_streaming.py -q`
Expected: FAIL because PR fields, messages, and language helper do not exist.

- [ ] **Step 3: Implement request types and reusable PR context preparation**

```python
class IssueDiagnosisMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=100000)

class IssueDiagnosisRequest(BaseModel):
    data_source_type: Literal["pr_pipeline", "ci_job", "commit", "manual"]
    pr_number: int | None = Field(None, gt=0)
    conversation_history: list[IssueDiagnosisMessage] = Field(default_factory=list, max_length=20)
```

Add `PRDiagnosisService.prepare_context()` to perform the existing PR/check/log/workflow collection and return `(context, system_prompt, pr_title)`. Make `diagnose()` call it so the old endpoint keeps its behavior. Route the new request fields into `stream_diagnose()` and append a final Chinese-language instruction after any configured skill prompt.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests/test_issue_diagnosis_streaming.py -q`
Expected: schema and prompt tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/issue_diagnosis.py backend/app/services/pr_diagnosis.py backend/app/services/issue_diagnosis.py backend/app/api/v1/issue_diagnosis.py backend/tests/test_issue_diagnosis_streaming.py
git commit -m "feat: unify issue diagnosis request context"
```

### Task 2: Completion-aware streaming and automatic continuation

**Files:**
- Modify: `backend/app/services/llm_client.py`
- Modify: `backend/app/services/issue_diagnosis.py`
- Test: `backend/tests/test_issue_diagnosis_streaming.py`

**Interfaces:**
- Consumes: provider streaming SDK chunks and prepared chat messages.
- Produces: `LLMStreamChunk(content: str = "", finish_reason: str | None = None)` and final SSE summary fields `finish_reason` and `continuation_count`.

- [ ] **Step 1: Write failing stream tests**

```python
@pytest.mark.asyncio
async def test_stream_continues_after_length_finish(fake_service):
    fake_service.llm_client.responses = [
        [LLMStreamChunk("第一部分"), LLMStreamChunk(finish_reason="length")],
        [LLMStreamChunk("第二部分"), LLMStreamChunk(finish_reason="stop")],
    ]
    events = [event async for event in fake_service.stream_diagnose(**request_args)]
    assert "".join(e["data"]["content"] for e in events if e["event"] == "chunk") == "第一部分第二部分"
    assert events[-1]["data"]["continuation_count"] == 1

@pytest.mark.asyncio
async def test_empty_stream_returns_error(fake_service):
    fake_service.llm_client.responses = [[LLMStreamChunk(finish_reason="stop")]]
    events = [event async for event in fake_service.stream_diagnose(**request_args)]
    assert events[-1] == {"event": "error", "data": {"message": "AI 未返回分析内容，请稍后重试"}}
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_issue_diagnosis_streaming.py -q`
Expected: FAIL because stream chunks have no finish reason and no continuation loop.

- [ ] **Step 3: Implement stream metadata and continuation**

```python
@dataclass
class LLMStreamChunk:
    content: str = ""
    finish_reason: str | None = None
```

Make OpenAI-compatible clients emit content and final finish reason. Make Anthropic emit `stop_reason` from its final message. In `IssueDiagnosisService`, send prepared messages, stream the first response immediately, and on `length` append the generated assistant text plus a Chinese continuation instruction. Buffer only continuation attempts, remove suffix/prefix overlap, emit the remaining text, and stop after two continuations.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests/test_issue_diagnosis_streaming.py -q`
Expected: all stream tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/llm_client.py backend/app/services/issue_diagnosis.py backend/tests/test_issue_diagnosis_streaming.py
git commit -m "fix: complete issue diagnosis streams"
```

### Task 3: Robust frontend SSE parser

**Files:**
- Create: `frontend/src/services/sseParser.ts`
- Create: `frontend/src/services/sseParser.test.ts`
- Modify: `frontend/src/services/issueDiagnosis.ts`
- Modify: `frontend/package.json`
- Modify: `frontend/pnpm-lock.yaml`

**Interfaces:**
- Consumes: decoded response text fragments.
- Produces: `SSEParser.push(fragment)` and `SSEParser.finish(fragment)` returning `{ event, data }[]`.

- [ ] **Step 1: Add Vitest and write failing parser tests**

```typescript
it('preserves events split across network and UTF-8 boundaries', () => {
  const parser = new SSEParser()
  expect(parser.push('event: chunk\ndata: {"content":"问')).toEqual([])
  expect(parser.push('题"}\n\nevent: done\ndata: {"chunk_count":1}')).toEqual([
    { event: 'chunk', data: '{"content":"问题"}' },
  ])
  expect(parser.finish()).toEqual([
    { event: 'done', data: '{"chunk_count":1}' },
  ])
})

it('joins multiline data and handles CRLF', () => {
  const parser = new SSEParser()
  expect(parser.finish('event: chunk\r\ndata: line1\r\ndata: line2\r\n\r\n')).toEqual([
    { event: 'chunk', data: 'line1\nline2' },
  ])
})
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pnpm test -- sseParser.test.ts`
Expected: FAIL because `SSEParser` does not exist.

- [ ] **Step 3: Implement event-boundary parsing and decoder flush**

```typescript
export class SSEParser {
  private buffer = ''
  push(fragment: string): SSEEvent[] { this.buffer += fragment; return this.drain(false) }
  finish(fragment = ''): SSEEvent[] { this.buffer += fragment; return this.drain(true) }
}
```

Parse blank-line-delimited events, normalize CRLF, join repeated `data:` lines, and process the final unterminated event. In `streamDiagnosis`, call `decoder.decode(value, { stream: true })` for chunks and `parser.finish(decoder.decode())` at EOF. Treat EOF without `done` or `error` as a Chinese interruption error.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pnpm test -- sseParser.test.ts`
Expected: parser tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/sseParser.ts frontend/src/services/sseParser.test.ts frontend/src/services/issueDiagnosis.ts frontend/package.json frontend/pnpm-lock.yaml
git commit -m "fix: parse complete diagnosis SSE events"
```

### Task 4: Multi-turn follow-up UI

**Files:**
- Create: `frontend/src/services/issueDiagnosisConversation.ts`
- Create: `frontend/src/services/issueDiagnosisConversation.test.ts`
- Modify: `frontend/src/hooks/useIssueDiagnosis.ts`
- Modify: `frontend/src/components/StreamMarkdownRenderer.tsx`
- Modify: `frontend/src/pages/IssueDiagnosis.tsx`

**Interfaces:**
- Consumes: the initial request, existing assistant/user turns, and a new question.
- Produces: `buildFollowUpRequest()` plus page state `conversation`, `followUpQuestion`, and `handleFollowUp`.

- [ ] **Step 1: Write a failing request-construction test**

```typescript
it('sends the complete conversation with a follow-up', () => {
  const request = buildFollowUpRequest(
    { data_source_type: 'pr_pipeline', pr_number: 12 },
    [{ role: 'assistant', content: '初始分析' }, { role: 'user', content: '为什么？' }, { role: 'assistant', content: '解释' }],
    '如何修复？',
  )
  expect(request.conversation_history).toEqual([
    { role: 'assistant', content: '初始分析' },
    { role: 'user', content: '为什么？' },
    { role: 'assistant', content: '解释' },
    { role: 'user', content: '如何修复？' },
  ])
})
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pnpm test -- issueDiagnosisConversation.test.ts`
Expected: FAIL because the helper does not exist.

- [ ] **Step 3: Implement conversation state and UI**

```typescript
export function buildFollowUpRequest(
  base: IssueDiagnosisRequest,
  conversation: DiagnosisMessage[],
  question: string,
): IssueDiagnosisRequest {
  return { ...base, conversation_history: [...conversation, { role: 'user', content: question.trim() }] }
}
```

Remove the issue page's synchronous `diagnosePR()` branch. Store the initial request for follow-ups, append every streamed chunk only to the active assistant turn, save history only after the initial turn, and expose a follow-up text area/button after initial completion. Render conversation turns with clear `AI 分析` and `追问` labels.

- [ ] **Step 4: Run frontend tests, build, and lint**

Run: `pnpm test`
Expected: all Vitest tests PASS.

Run: `pnpm run build`
Expected: TypeScript and Vite build PASS.

Run: `pnpm run lint`
Expected: ESLint exits 0.

- [ ] **Step 5: Run backend regression tests**

Run: `python -m pytest tests/test_issue_diagnosis_streaming.py -q`
Expected: focused backend tests PASS.

Run: `python -m pytest`
Expected: full backend suite PASS with required test environment variables configured.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/services/issueDiagnosisConversation.ts frontend/src/services/issueDiagnosisConversation.test.ts frontend/src/hooks/useIssueDiagnosis.ts frontend/src/components/StreamMarkdownRenderer.tsx frontend/src/pages/IssueDiagnosis.tsx
git commit -m "feat: add contextual diagnosis follow-ups"
```
