import { describe, expect, it } from 'vitest'

import { formatApiError } from './issueDiagnosis'


describe('formatApiError', () => {
  it('normalizes FastAPI validation details to text', () => {
    expect(formatApiError([
      { loc: ['body', 'conversation_history'], msg: 'List should have at most 50 items' },
    ], '请求失败')).toBe('List should have at most 50 items')
  })

  it('keeps safe string details', () => {
    expect(formatApiError('PR 编号无效', '请求失败')).toBe('PR 编号无效')
  })
})
