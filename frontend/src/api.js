export async function request(path, options = {}) {
  const response = await fetch(path, options);
  const json = response.headers.get('content-type')?.includes('json');
  const data = json ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = data?.detail;
    const message = typeof detail === 'string' ? detail : detail?.message || (Array.isArray(detail) ? detail.map(x => x.msg).join(', ') : `Request failed (${response.status})`);
    const error = new Error(message); error.status = response.status; throw error;
  }
  if (data && typeof data === 'object' && response.headers.get('X-Offline-Cache')) data.offline = true;
  return data;
}
export const jsonRequest = (path, method, data) => request(path, {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
export const safeUrl = value => /^https?:\/\//i.test(value || '') ? value : undefined;
