/** 覆盖率热力图配色 — 红<50 / 黄50-80 / 绿≥80 */
export function heatColor(percent: number): { background: string; color: string } {
  if (percent >= 80) return { background: '#f6ffed', color: '#237804' }
  if (percent >= 50) return { background: '#fffbe6', color: '#ad6800' }
  return { background: '#fff1f0', color: '#cf1322' }
}

/** 从 commit 值提取 SHA 字符串（兼容 string 和 {sha,...} 对象） */
export function commitSha(commit: unknown): string | null {
  if (!commit) return null
  if (typeof commit === 'string') return commit
  if (typeof commit === 'object' && commit !== null && 'sha' in commit) {
    return String((commit as Record<string, unknown>).sha)
  }
  return null
}

/** GitHub blob URL 拼接 */
export function githubBlobUrl(commit: unknown, path: string, owner = 'vllm-project', repo = 'vllm-ascend'): string {
  const sha = commitSha(commit)
  if (!sha) return ''
  return `https://github.com/${owner}/${repo}/blob/${sha}/${path}`
}

/** E2E 测试文件 filepath → 仓库内完整路径 */
export function e2eFullRepoPath(filepath: string): string {
  return `tests/e2e/pull_request/${filepath}`
}
