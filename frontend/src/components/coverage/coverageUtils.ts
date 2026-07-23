/** 覆盖率热力图配色 — 红<50 / 黄50-80 / 绿≥80 */
export function heatColor(percent: number): { background: string; color: string } {
  if (percent >= 80) return { background: '#f6ffed', color: '#237804' }
  if (percent >= 50) return { background: '#fffbe6', color: '#ad6800' }
  return { background: '#fff1f0', color: '#cf1322' }
}

/** GitHub blob URL 拼接 */
export function githubBlobUrl(commit: string | null | undefined, path: string, owner = 'vllm-project', repo = 'vllm-ascend'): string {
  if (!commit) return ''
  return `https://github.com/${owner}/${repo}/blob/${commit}/${path}`
}

/** E2E 测试文件 filepath → 仓库内完整路径 */
export function e2eFullRepoPath(filepath: string): string {
  return `tests/e2e/pull_request/${filepath}`
}
