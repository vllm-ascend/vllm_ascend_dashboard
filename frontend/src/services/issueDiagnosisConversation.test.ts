import { describe, expect, it } from 'vitest'

import { buildFollowUpRequest, canAskFollowUp } from './issueDiagnosisConversation'


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

  it('drops an empty failed assistant turn before retrying', () => {
    const request = buildFollowUpRequest(
      { data_source_type: 'manual', user_prompt: '分析问题' },
      [
        { role: 'assistant', content: '初始分析' },
        { role: 'user', content: '失败的追问' },
        { role: 'assistant', content: '' },
      ],
      '重新追问',
    )

    expect(request.conversation_history).toEqual([
      { role: 'assistant', content: '初始分析' },
      { role: 'user', content: '失败的追问' },
      { role: 'user', content: '重新追问' },
    ])
  })

  it('stops before the API conversation limit', () => {
    const messages = Array.from({ length: 49 }, (_, index) => ({
      role: index % 2 ? 'user' as const : 'assistant' as const,
      content: `消息 ${index}`,
    }))

    expect(canAskFollowUp(messages)).toBe(false)
  })
})
