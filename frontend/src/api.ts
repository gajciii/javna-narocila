import type { Filters } from './types';
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
    const isForm = options.body instanceof FormData;
    const csrf = document.cookie.split('; ').find(value => value.startsWith('csrftoken='))?.slice('csrftoken='.length);
    const unsafe = !['GET', 'HEAD', 'OPTIONS'].includes((options.method || 'GET').toUpperCase());
    const response = await fetch(`/api${path}`, { ...options, headers: { ...(isForm ? {} : { 'Content-Type': 'application/json' }),
        ...(csrf && unsafe ? { 'X-CSRFToken': decodeURIComponent(csrf) } : {}), ...options.headers } });
    if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        if (body.code === 'login_required') window.dispatchEvent(new Event('account-session-expired'));
        const flatten = (value: unknown): string => typeof value === 'string' ? value : Array.isArray(value) ? value.map(flatten).join(' ') : value && typeof value === 'object' ? Object.values(value).map(flatten).join(' ') : '';
        throw new Error(flatten(body.error || body.detail || body.message || body) || `Zahteve ni bilo mogoče zaključiti (${response.status}).`);
    }
    if (unsafe && ['/admin/pipeline/login', '/admin/pipeline/logout'].includes(path)) window.dispatchEvent(new Event('account-session-changed'));
    if (response.status === 204)
        return undefined as T;
    return response.json() as Promise<T>;
}
export function post<T>(path: string, body: unknown = {}) { return api<T>(path, { method: 'POST', body: JSON.stringify(body) }); }
export function filterQuery(filters: Filters): string {
    const query = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '' && (!Array.isArray(value) || value.length))
            query.set(key, Array.isArray(value) ? value.join(',') : String(value));
    });
    return query.toString();
}
