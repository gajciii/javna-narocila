import { useState, type FormEvent } from 'react';
import { ArrowLeft, LoaderCircle, Radar } from 'lucide-react';
import { post } from './api';

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
    const [error, setError] = useState('');
    const submit = async (event: FormEvent) => {
        event.preventDefault(); setError('');
        if (register && password !== confirmation) { setError('Gesli se ne ujemata.'); return; }
        setBusy(true);
        try {
            const session = await post<AccountSession>(register ? '/auth/register' : '/auth/login', register
                ? { email: username, password, password_confirm: confirmation } : { username, password });
            setPassword(''); setConfirmation(''); onSuccess(session);
        } catch (e) { setError((e as Error).message); }
        finally { setBusy(false); }
    };
    return <main className="account-page"><a className="brand" href="#/"><Radar size={28}/><span>Razp<span>Izi</span></span></a><section className="surface account-card"><h1>{register ? 'Ustvarite račun' : 'Prijava'}</h1><p>{register ? 'Shranite svoja podjetja in poiščite razpise, ki vam ustrezajo.' : 'Nadaljujte s svojimi podjetji in shranjenimi razpisi.'}</p><form onSubmit={submit}>
        <label className="field"><span>{register ? 'E-poštni naslov' : 'E-pošta ali uporabniško ime'}</span><input autoFocus required type={register ? 'email' : 'text'} autoComplete="username" maxLength={150} value={username} onChange={e => setUsername(e.target.value)}/></label>
        <label className="field"><span>Geslo</span><input required type="password" autoComplete={register ? 'new-password' : 'current-password'} minLength={register ? 8 : undefined} maxLength={1024} value={password} onChange={e => setPassword(e.target.value)}/></label>
        {register && <><p className="section-help">Vsaj 8 znakov. Geslo naj ne bo pogosto, samo številčno ali podobno vašemu e-poštnemu naslovu.</p><label className="field"><span>Ponovite geslo</span><input required type="password" autoComplete="new-password" maxLength={1024} value={confirmation} onChange={e => setConfirmation(e.target.value)}/></label></>}
        {error && <div className="error-banner" role="alert">{error}</div>}
        <button className="button primary full-width" disabled={busy}>{busy && <LoaderCircle size={16} className="spin"/>}{register ? 'Registriraj se' : 'Prijavi se'}</button>
    </form><p>{register ? 'Že imate račun?' : 'Še nimate računa?'} <a className="text-link" href={register ? '#/prijava' : '#/registracija'}>{register ? 'Prijavite se' : 'Registrirajte se'}</a></p></section><a className="text-link" href="#/"><ArrowLeft size={15}/>Na domačo stran</a></main>;
}
