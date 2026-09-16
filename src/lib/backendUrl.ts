/**
 * Helper to get the active Python backend URL.
 * Evaluated at request time so dynamic port assignments (e.g. in Electron) are respected.
 */
export function getPythonBackendUrl(): string {
  return process.env.PYTHON_BACKEND_URL || 'http://127.0.0.1:4455';
}
