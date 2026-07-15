import { describe, expect, it } from 'vitest'

import { buildFollowUpRequest } from './issueDiagnosisConversation'


describe('buildFollowUpRequest', () => {
  it('sends the complete conversation with a follow-up', () => {
    const request = buildFollowUpRequest(
      { data_source_type: 'pr_pipeline', pr_number: 12 },
      [
        { role: 'assistant', content: '初始分析' },
        { role: 'user', content: '为什么？' },
        { role: 'assistant', content: '解释' },
      ],
      '  如何修复？  ',
    )

    expect(request.conversation_history).toEqual([
      { role: 'assistant', content: '初始分析' },
      { role: 'user', content: '为什么？' },
      { role: 'assistant', content: '解释' },
      { role: 'user', content: '如何修复？' },
    ])
  })
})
