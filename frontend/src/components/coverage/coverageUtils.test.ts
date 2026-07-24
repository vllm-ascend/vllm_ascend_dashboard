import { describe, expect, it } from 'vitest'

import { commitSha, githubBlobUrl, heatColor, e2eFullRepoPath } from './coverageUtils'

describe('commitSha', () => {
  it('extracts SHA from a string', () => {
    expect(commitSha('abc123')).toBe('abc123')
  })

  it('extracts SHA from an object with sha property', () => {
    expect(commitSha({ sha: 'def456', subject: 'fix: something' })).toBe('def456')
  })

  it('extracts SHA from a full commit object', () => {
    const commit = {
      sha: 'b4587e0a2a7fc75ab4feb95f1360f1b5eb635d3b',
      subject: '[BugFix] Fix something',
      author_name: 'test',
      author_email: 'test@test.com',
      date: '2026-07-23T23:05:29+08:00',
    }
    expect(commitSha(commit)).toBe('b4587e0a2a7fc75ab4feb95f1360f1b5eb635d3b')
  })

  it('returns null for null', () => {
    expect(commitSha(null)).toBeNull()
  })

  it('returns null for undefined', () => {
    expect(commitSha(undefined)).toBeNull()
  })

  it('returns null for empty string', () => {
    expect(commitSha('')).toBeNull()
  })

  it('returns null for object without sha property', () => {
    expect(commitSha({ foo: 'bar' })).toBeNull()
  })

  it('returns null for number', () => {
    expect(commitSha(42)).toBeNull()
  })
})

describe('githubBlobUrl', () => {
  it('generates URL from string commit', () => {
    expect(githubBlobUrl('abc123', 'vllm_ascend/platform.py')).toBe(
      'https://github.com/vllm-project/vllm-ascend/blob/abc123/vllm_ascend/platform.py',
    )
  })

  it('generates URL from object commit (Bug: repo_commit was object, not string)', () => {
    const commit = { sha: 'b4587e0a2a', subject: 'test' }
    expect(githubBlobUrl(commit, 'vllm_ascend/platform.py')).toBe(
      'https://github.com/vllm-project/vllm-ascend/blob/b4587e0a2a/vllm_ascend/platform.py',
    )
  })

  it('returns empty string for null commit', () => {
    expect(githubBlobUrl(null, 'vllm_ascend/platform.py')).toBe('')
  })

  it('returns empty string for undefined commit', () => {
    expect(githubBlobUrl(undefined, 'vllm_ascend/platform.py')).toBe('')
  })

  it('returns empty string for object without sha', () => {
    expect(githubBlobUrl({ foo: 'bar' }, 'vllm_ascend/platform.py')).toBe('')
  })

  it('uses custom owner and repo', () => {
    expect(githubBlobUrl('abc', 'path/file.py', 'myorg', 'myrepo')).toBe(
      'https://github.com/myorg/myrepo/blob/abc/path/file.py',
    )
  })
})

describe('heatColor', () => {
  it('returns green for >= 80', () => {
    expect(heatColor(80)).toEqual({ background: '#f6ffed', color: '#237804' })
    expect(heatColor(100)).toEqual({ background: '#f6ffed', color: '#237804' })
  })

  it('returns yellow for 50-79', () => {
    expect(heatColor(50)).toEqual({ background: '#fffbe6', color: '#ad6800' })
    expect(heatColor(79)).toEqual({ background: '#fffbe6', color: '#ad6800' })
  })

  it('returns red for < 50', () => {
    expect(heatColor(0)).toEqual({ background: '#fff1f0', color: '#cf1322' })
    expect(heatColor(49)).toEqual({ background: '#fff1f0', color: '#cf1322' })
  })
})

describe('e2eFullRepoPath', () => {
  it('prepends tests/e2e/pull_request/', () => {
    expect(e2eFullRepoPath('one_card/test_batch_invariant.py')).toBe(
      'tests/e2e/pull_request/one_card/test_batch_invariant.py',
    )
  })

  it('handles nested paths', () => {
    expect(e2eFullRepoPath('four_card/spec_decode/test_mtp.py')).toBe(
      'tests/e2e/pull_request/four_card/spec_decode/test_mtp.py',
    )
  })
})
