const configuredBasePath = import.meta.env.VITE_APP_BASE_PATH || '/'

export const appBasePath = configuredBasePath === '/'
  ? '/'
  : `/${configuredBasePath.replace(/^\/+|\/+$/g, '')}`

export function appUrl(path: string) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return appBasePath === '/' ? normalizedPath : `${appBasePath}${normalizedPath}`
}
