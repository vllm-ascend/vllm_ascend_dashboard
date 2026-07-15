export interface SSEEvent {
  event: string
  data: string
}

export class SSEParser {
  private buffer = ''

  push(fragment: string): SSEEvent[] {
    this.buffer += fragment
    return this.drain(false)
  }

  finish(fragment = ''): SSEEvent[] {
    this.buffer += fragment
    return this.drain(true)
  }

  private drain(flushTail: boolean): SSEEvent[] {
    const events: SSEEvent[] = []
    let boundary = this.buffer.match(/\r?\n\r?\n/)

    while (boundary?.index !== undefined) {
      const block = this.buffer.slice(0, boundary.index)
      this.buffer = this.buffer.slice(boundary.index + boundary[0].length)
      const event = this.parseBlock(block)
      if (event) events.push(event)
      boundary = this.buffer.match(/\r?\n\r?\n/)
    }

    if (flushTail && this.buffer.trim()) {
      const event = this.parseBlock(this.buffer)
      if (event) events.push(event)
      this.buffer = ''
    }

    return events
  }

  private parseBlock(block: string): SSEEvent | null {
    let event = 'message'
    const data: string[] = []

    for (const line of block.split(/\r?\n/)) {
      if (!line || line.startsWith(':')) continue
      const separator = line.indexOf(':')
      const field = separator === -1 ? line : line.slice(0, separator)
      const rawValue = separator === -1 ? '' : line.slice(separator + 1)
      const value = rawValue.startsWith(' ') ? rawValue.slice(1) : rawValue
      if (field === 'event') event = value
      if (field === 'data') data.push(value)
    }

    return data.length ? { event, data: data.join('\n') } : null
  }
}
