export class AdminError extends Error { constructor(message: string, public status: number) { super(message); } }
export async function request<T>(path: string, options: RequestInit = {}, csrf = ''): Promise<T> {
    const response = await fetch(`/api/admin/pipeline${path}`, { ...options, credentials: 'same-origin',
        headers: { ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...(csrf ? { 'X-CSRFToken': csrf } : {}), ...options.headers } });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new AdminError(data.error || data.detail || 'Zahteve ni bilo mogoče zaključiti.', response.status);
    return data as T;
}
