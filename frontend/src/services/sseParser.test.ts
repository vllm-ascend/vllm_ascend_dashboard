import { describe, expect, it } from 'vitest'

import { SSEParser } from './sseParser'


describe('SSEParser', () => {
  it('preserves events split across network boundaries and flushes the tail', () => {
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

    expect(
      parser.finish('event: chunk\r\ndata: line1\r\ndata: line2\r\n\r\n'),
    ).toEqual([{ event: 'chunk', data: 'line1\nline2' }])
  })
})
