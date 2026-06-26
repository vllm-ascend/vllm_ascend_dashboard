# 问题自动定位（Issue Diagnosis）实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在CI Board的失败Job上增加"问题定位"按钮，弹出诊断Modal，通过系统LLM + Skill进行流式AI根因分析。

**Architecture:** 后端新增`issue_diagnosis` API模块（SSE流式响应），LLM Client新增streaming方法。前端新增`IssueDiagnosisModal`组件嵌入JobDetail页面，通过fetch+ReadableStream消费SSE。

**Tech Stack:** FastAPI StreamingResponse, OpenAI/Anthropic/Qwen async streaming SDK, React fetch ReadableStream, Ant Design Modal, ReactMarkdown

---

### Task 1: 后端 - LLM Client 流式方法

**Files:**
- Modify: `backend/app/services/llm_client.py`

**Step 1: Add `generate_stream` abstract method to `BaseLLMClient`**

After the existing `generate` method (line ~47), add:

```python
    async def generate_stream(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        raise NotImplementedError
```

**Step 2: Add `generate_stream` to `OpenAIClient`**

After the `generate` method in `OpenAIClient` (after line ~86), add:

```python
    async def generate_stream(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.api_base or "https://api.openai.com/v1"
            )

            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )

            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
        except Exception as e:
            logger.error(f"OpenAI streaming failed: {e}")
            raise LLMError(f"OpenAI streaming failed: {str(e)}")
```

**Step 3: Add `generate_stream` to `AnthropicClient`**

After the `generate` method in `AnthropicClient` (after line ~134), add:

```python
    async def generate_stream(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        try:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(
                api_key=self.api_key,
                base_url=self.api_base or "https://api.anthropic.com"
            )

            system_prompt = ""
            user_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    system_prompt = msg["content"]
                else:
                    user_messages.append(msg)

            async with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=user_messages,
                temperature=temperature,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as e:
            logger.error(f"Anthropic streaming failed: {e}")
            raise LLMError(f"Anthropic streaming failed: {str(e)}")
```

**Step 4: Add `generate_stream` to `QwenClient`**

After the `generate` method in `QwenClient` (after line ~172), add:

```python
    async def generate_stream(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.api_base or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            )

            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )

            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
        except Exception as e:
            logger.error(f"Qwen streaming failed: {e}")
            raise LLMError(f"Qwen streaming failed: {str(e)}")
```

**Step 5: Add `generate_stream` to `LLMClient` (unified entry)**

After the `generate` method in `LLMClient` (after line ~247), add:

```python
    async def generate_stream(
        self,
        provider: str,
        model: str,
        api_key: str,
        api_base: Optional[str] = None,
        system_prompt: str = "",
        user_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        if not api_key:
            raise LLMError(f"API Key not configured for provider: {provider}")

        client = create_client(provider, api_key, api_base)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        async for chunk in client.generate_stream(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            yield chunk
```

**Step 6: Commit**

```bash
git add backend/app/services/llm_client.py
git commit -m "feat: add streaming generate methods to LLM client for all providers"
```

---

### Task 2: 后端 - Pydantic Schemas

**Files:**
- Create: `backend/app/schemas/issue_diagnosis.py`
- Modify: `backend/app/schemas/__init__.py`

**Step 1: Create schema file**

Create `backend/app/schemas/issue_diagnosis.py`:

```python
from pydantic import BaseModel, Field
from typing import Optional


class IssueDiagnosisRequest(BaseModel):
    data_source_type: str = Field(
        ...,
        description="数据源类型: ci_job, commit, manual",
    )
    job_id: Optional[int] = Field(
        None,
        description="CI Job ID (data_source_type=ci_job时必填)",
    )
    run_id: Optional[int] = Field(
        None,
        description="CI Run ID (用于commit数据源)",
    )
    commit_sha: Optional[str] = Field(
        None,
        description="Commit SHA (data_source_type=commit时可选)",
    )
    user_prompt: Optional[str] = Field(
        None,
        description="用户补充提示词",
    )


class CIJobOption(BaseModel):
    job_id: int
    run_id: int
    workflow_name: str
    job_name: str
    conclusion: str
    completed_at: Optional[str] = None


class CommitOption(BaseModel):
    sha: str
    message: str
    committed_at: Optional[str] = None
    run_id: Optional[int] = None
    run_number: Optional[int] = None
```

**Step 2: Update schemas/__init__.py**

Read `backend/app/schemas/__init__.py` and add import for the new schemas module.

**Step 3: Commit**

```bash
git add backend/app/schemas/issue_diagnosis.py backend/app/schemas/__init__.py
git commit -m "feat: add issue diagnosis pydantic schemas"
```

---

### Task 3: 后端 - Issue Diagnosis Service

**Files:**
- Create: `backend/app/services/issue_diagnosis.py`

**Step 1: Create service file**

Create `backend/app/services/issue_diagnosis.py` with the full implementation. The service:
- `_get_llm_config`: fetches active LLMProviderConfig from DB
- `_get_system_prompt`: auto-matches skill by data_source_type (ci_job→ci_failure_analysis)
- `_collect_ci_job_context`: reuses FailureAnalysisService._build_job_context
- `_collect_commit_context`: builds commit context from CIResult
- `stream_diagnose`: main async generator yielding SSE events
- `get_failed_ci_jobs`: returns list of failed CIJob options
- `get_recent_commits`: returns list of recent CIResult options

Key method `stream_diagnose`:
1. Get LLM config + system prompt
2. Collect context based on data_source_type
3. Build full user prompt (context + user supplementary prompt)
4. Yield meta event (provider/model info)
5. Stream LLM chunks via `LLMClient.generate_stream()`
6. Yield done event with duration/count stats
7. Yield error event on failure

**Step 2: Commit**

```bash
git add backend/app/services/issue_diagnosis.py
git commit -m "feat: add issue diagnosis service with SSE streaming support"
```

---

### Task 4: 后端 - API Routes + Router Registration

**Files:**
- Create: `backend/app/api/v1/issue_diagnosis.py`
- Modify: `backend/app/main.py`

**Step 1: Create API route file**

Create `backend/app/api/v1/issue_diagnosis.py` with:
- `POST /diagnose` - SSE StreamingResponse (CurrentAdminUser required)
- `GET /data-sources/ci-jobs` - list failed CI jobs (CurrentAdminUser required)
- `GET /data-sources/commits` - list recent commits (CurrentAdminUser required)

The `/diagnose` endpoint uses `StreamingResponse` with `text/event-stream` media type. The async generator formats SSE events as `event: xxx\ndata: json\n\n`.

**Step 2: Register router in main.py**

Add to `backend/app/main.py`:
- Import: `from app.api.v1 import issue_diagnosis`
- Register: `app.include_router(issue_diagnosis.router, prefix="/api/v1/issue-diagnosis", tags=["问题定位"])`

**Step 3: Commit**

```bash
git add backend/app/api/v1/issue_diagnosis.py backend/app/main.py
git commit -m "feat: add issue diagnosis API endpoints with SSE streaming"
```

---

### Task 5: 前端 - API Service + SSE Consumer

**Files:**
- Create: `frontend/src/services/issueDiagnosis.ts`

**Step 1: Create API service file**

Create `frontend/src/services/issueDiagnosis.ts` with:
- Types: `IssueDiagnosisRequest`, `CIJobOption`, `CommitOption`
- `getFailedCIJobs(daysBack)` - GET request for CI job options
- `getRecentCommits(daysBack)` - GET request for commit options
- `streamDiagnosis(request, onChunk, onMeta, onDone, onError)` - SSE consumer using `fetch` + `ReadableStream`

The SSE consumer uses `fetch` (not EventSource) because:
1. Need POST method
2. Need Bearer auth header
3. EventSource only supports GET without custom headers

The parser handles SSE format by buffering lines and parsing `event:` and `data:` prefixes.

**Step 2: Commit**

```bash
git add frontend/src/services/issueDiagnosis.ts
git commit -m "feat: add issue diagnosis frontend API service with SSE streaming"
```

---

### Task 6: 前端 - StreamMarkdownRenderer 组件

**Files:**
- Create: `frontend/src/components/StreamMarkdownRenderer.tsx`

**Step 1: Create streaming markdown renderer**

Create `frontend/src/components/StreamMarkdownRenderer.tsx` with:
- Props: `content`, `isStreaming`, `meta`, `summary`
- Auto-scroll to bottom during streaming (with manual scroll override)
- Meta info bar showing provider/model + duration/stats
- ReactMarkdown rendering with remarkGfm
- Streaming cursor indicator (`▊` character) when streaming
- Empty state with prompt text

**Step 2: Commit**

```bash
git add frontend/src/components/StreamMarkdownRenderer.tsx
git commit -m "feat: add streaming markdown renderer component"
```

---

### Task 7: 前端 - IssueDiagnosisModal 组件

**Files:**
- Create: `frontend/src/components/IssueDiagnosisModal.tsx`

**Step 1: Create the diagnosis modal**

Create `frontend/src/components/IssueDiagnosisModal.tsx` with:
- Props: `open`, `onClose`, `initialJobId` (pre-selected when opened from JobDetail)
- Two-column layout (Modal width 1000px):
  - Left (320px): data source type select, CI Job/Commit select (lazy-loaded on dropdown open), user prompt textarea, start/copy/export buttons
  - Right (flex): StreamMarkdownRenderer
- State: dataSourceType, selectedJobId, selectedCommitSha, userPrompt, isStreaming, streamContent, meta, summary, error
- Lazy-load data source options on dropdown open
- Copy to clipboard + export as .md file
- Reset state on close

**Step 2: Commit**

```bash
git add frontend/src/components/IssueDiagnosisModal.tsx
git commit -m "feat: add issue diagnosis modal with two-column layout"
```

---

### Task 8: 前端 - 集成到 JobDetail 页面

**Files:**
- Modify: `frontend/src/pages/JobDetail.tsx`

**Step 1: Add imports and state**

Add at the top of imports:
```typescript
import { SearchOutlined } from '@ant-design/icons'
import IssueDiagnosisModal from '../components/IssueDiagnosisModal'
```

Add state inside the component:
```typescript
const [diagnosisModalOpen, setDiagnosisModalOpen] = useState(false)
```

**Step 2: Add "问题定位" button in the failed job card**

In the `extra` prop of the failure diagnosis Card (around line 224), add a button alongside the existing "开始分析"/"重新分析" button:

```typescript
extra={
  <Space>
    <Button
      icon={<SearchOutlined />}
      onClick={() => setDiagnosisModalOpen(true)}
      size="small"
    >
      问题定位
    </Button>
    <Button
      icon={<RobotOutlined />}
      loading={analyzeMutation.isPending}
      onClick={analysis ? handleReAnalyze : handleAnalyze}
      type="primary"
      size="small"
    >
      {analysis ? '重新分析' : '开始分析'}
    </Button>
  </Space>
}
```

**Step 3: Add IssueDiagnosisModal component**

Add at the end of the JSX (after the Steps card, before closing `</div>`):

```typescript
{isFailed && (
  <IssueDiagnosisModal
    open={diagnosisModalOpen}
    onClose={() => setDiagnosisModalOpen(false)}
    initialJobId={jobIdNum}
  />
)}
```

**Step 4: Commit**

```bash
git add frontend/src/pages/JobDetail.tsx
git commit -m "feat: integrate issue diagnosis modal into JobDetail page"
```

---

### Task 9: 验证 - 启动并测试

**Step 1: Start backend**

Run: `cd backend && python -m uvicorn app.main:app --reload --port 8000`

Expected: Server starts, `/docs` shows new `/issue-diagnosis` endpoints

**Step 2: Start frontend**

Run: `cd frontend && npm run dev`

Expected: Dev server starts, JobDetail page for failed jobs shows "问题定位" button

**Step 3: Test SSE endpoint manually**

Use curl or browser:
```bash
curl -X POST http://localhost:8000/api/v1/issue-diagnosis/diagnose \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"data_source_type": "manual", "user_prompt": "test"}'
```

Expected: SSE stream with chunk/meta/done events

**Step 4: Test frontend integration**

Navigate to a failed Job detail page, click "问题定位" button, verify Modal opens and streaming works.

**Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: any integration fixes for issue diagnosis feature"
```
