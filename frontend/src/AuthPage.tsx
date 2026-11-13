import { useRef, useState, type FormEvent } from 'react';
import { ArrowLeft, LoaderCircle, Radar } from 'lucide-react';
import { post } from './api';
import './auth.css';

type AccountField = 'username' | 'password' | 'confirmation';
type FieldErrors = Partial<Record<AccountField, string>>;

export interface AccountSession {
    authenticated: boolean;
    csrf_token?: string;
    user: { id: number; username: string; email: string; is_staff: boolean } | null;
}

export default function AuthPage({ register, onSuccess }: { register: boolean; onSuccess: (session: AccountSession) => void }) {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const [busy, setBusy] = useState(false);
    const [errors, setErrors] = useState<FieldErrors>({});
    const [formError, setFormError] = useState('');
    const form = useRef<HTMLFormElement>(null);
    const showErrors = (next: FieldErrors) => {
        setErrors(next);
        const first = (['username', 'password', 'confirmation'] as const).find(field => next[field]);
        if (first) form.current?.querySelector<HTMLInputElement>(`[name="${first}"]`)?.focus();
    };
    const clearError = (field: AccountField) => {
        setFormError('');
        setErrors(previous => ({ ...previous, [field]: undefined,
            ...(!register && field === 'username' ? { password: undefined } : {}) }));
    };
    const submit = async (event: FormEvent) => {
        event.preventDefault();
        if (busy) return;
        setFormError('');
        const next: FieldErrors = {};
        if (!username.trim()) next.username = register ? 'Vnesite e-poštni naslov.' : 'Vnesite e-pošto ali uporabniško ime.';
        else if (register && form.current?.elements.namedItem('username') instanceof HTMLInputElement
            && !(form.current.elements.namedItem('username') as HTMLInputElement).validity.valid) next.username = 'Vnesite veljaven e-poštni naslov.';
        if (!password) next.password = 'Vnesite geslo.';
        else if (register && password.length < 8) next.password = 'Geslo mora vsebovati vsaj 8 znakov.';
        if (register && !confirmation) next.confirmation = 'Ponovno vnesite geslo.';
        else if (register && password !== confirmation) next.confirmation = 'Gesli se ne ujemata.';
        showErrors(next);
        if (Object.keys(next).length) return;
        setBusy(true);
        try {
            const session = await post<AccountSession>(register ? '/auth/register' : '/auth/login', register
                ? { email: username.trim(), password, password_confirm: confirmation } : { username: username.trim(), password });
            setPassword(''); setConfirmation(''); onSuccess(session);
        } catch (e) {
            const message = (e as Error).message;
            if (!register && message.startsWith('Prijava ni uspela.')) showErrors({ password: message });
            else if (register && message === 'Gesli se ne ujemata.') showErrors({ confirmation: message });
            else if (register && /gesl|password/i.test(message)) showErrors({ password: message });
            else if (register && /e-pošt|email|e-mail/i.test(message)) showErrors({ username: message });
            else setFormError(message);
        }
        finally { setBusy(false); }
    };
    return <main className="account-page"><a className="brand" href="#/" aria-label="RazpIzi, domača stran"><Radar size={28}/><span>Razp<span>Izi</span></span></a><section className="surface account-card" aria-labelledby="account-title"><h1 id="account-title">{register ? 'Ustvarite račun' : 'Prijava'}</h1><p>{register ? 'Shranite svoja podjetja in poiščite razpise, ki vam ustrezajo.' : 'Nadaljujte s svojimi podjetji in shranjenimi razpisi.'}</p><form ref={form} noValidate onSubmit={submit} aria-busy={busy}>
        <label className="field" htmlFor="account-username"><span>{register ? 'E-poštni naslov' : 'E-pošta ali uporabniško ime'}</span><input id="account-username" name="username" autoFocus required type={register ? 'email' : 'text'} autoComplete={register ? 'email' : 'username'} maxLength={150} aria-invalid={!!errors.username} aria-describedby={errors.username ? 'account-username-error' : undefined} value={username} onChange={e => { setUsername(e.target.value); clearError('username'); }}/>{errors.username && <span className="account-field-error" id="account-username-error" role="alert">{errors.username}</span>}</label>
        <label className="field" htmlFor="account-password"><span>Geslo</span><input id="account-password" name="password" required type="password" autoComplete={register ? 'new-password' : 'current-password'} minLength={register ? 8 : undefined} maxLength={1024} aria-invalid={!!errors.password} aria-describedby={[register ? 'account-password-hint' : '', errors.password ? 'account-password-error' : ''].filter(Boolean).join(' ') || undefined} value={password} onChange={e => { setPassword(e.target.value); clearError('password'); }}/>{register && <span className="account-field-hint" id="account-password-hint">Vsaj 8 znakov. Geslo naj ne bo pogosto, samo številčno ali podobno vaši e-pošti.</span>}{errors.password && <span className="account-field-error" id="account-password-error" role="alert">{errors.password}</span>}</label>
        {register && <label className="field" htmlFor="account-confirmation"><span>Ponovite geslo</span><input id="account-confirmation" name="confirmation" required type="password" autoComplete="new-password" maxLength={1024} aria-invalid={!!errors.confirmation} aria-describedby={errors.confirmation ? 'account-confirmation-error' : undefined} value={confirmation} onChange={e => { setConfirmation(e.target.value); clearError('confirmation'); }}/>{errors.confirmation && <span className="account-field-error" id="account-confirmation-error" role="alert">{errors.confirmation}</span>}</label>}
        <button className="button primary full-width" disabled={busy}>{busy && <LoaderCircle size={16} className="spin"/>}{register ? 'Registriraj se' : 'Prijavi se'}</button>
        {formError && <p className="account-field-error account-form-error" role="alert">{formError}</p>}
    </form><p>{register ? 'Že imate račun?' : 'Še nimate računa?'} <a className="text-link" href={register ? '#/prijava' : '#/registracija'}>{register ? 'Prijavite se' : 'Registrirajte se'}</a></p></section><a className="text-link" href="#/"><ArrowLeft size={15}/>Na domačo stran</a></main>;
}
