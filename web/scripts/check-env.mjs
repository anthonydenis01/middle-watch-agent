const value = process.env.VITE_API_URL || ''
if (process.env.NETLIFY === 'true' || value) {
  let valid = false
  try {
    const url = new URL(value)
    valid = url.protocol === 'https:' && !url.username && !url.password &&
      !url.search && !url.hash && url.pathname === '/' && value === url.origin
  } catch { /* The safe error below intentionally omits the supplied value. */ }
  if (!valid) {
    throw new Error('Set VITE_API_URL to the public HTTPS API origin, without a trailing slash, path, credentials, or query.')
  }
}
