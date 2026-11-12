import { useEffect, useState, type FormEvent } from 'react';
import { LoaderCircle, Mail, Save } from 'lucide-react';
import { api } from './api';

type EmailSettings = { provider: 'smtp' | 'resend' | 'unavailable'; enabled: boolean; email: string; transport_ready: boolean; pending: number; failed: number; last_sent_at: string | null };

export default function EmailNotificationSettings() {
    const [settings, setSettings] = useState<EmailSettings | null>(null);
    const [email, setEmail] = useState('');
    const [enabled, setEnabled] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [message, setMessage] = useState('');
    const [revision, setRevision] = useState(0);
    useEffect(() => {
        let active = true;
        setError('');
        api<EmailSettings>('/notifications/email-settings').then(value => {
            if (active) { setSettings(value); setEmail(value.email); setEnabled(value.enabled); }
        }).catch(e => { if (active) setError((e as Error).message); });
        return () => { active = false; };
    }, [revision]);
    const save = async (event: FormEvent) => {
        event.preventDefault(); setBusy(true); setError(''); setMessage('');
        try {
            const result = await api<EmailSettings>('/notifications/email-settings', { method: 'PUT', body: JSON.stringify({ email, enabled }) });
            setSettings(result); setEmail(result.email); setEnabled(result.enabled);
            setMessage(result.enabled ? result.transport_ready ? 'E-poštna obvestila so vključena za prihodnje spremembe.' : 'Nastavitev je shranjena. Pošiljanje bo na voljo, ko bo nastavljeno na strežniku.' : 'E-poštna obvestila so izključena.');
        } catch (e) { setError((e as Error).message); }
        finally { setBusy(false); }
    };
    return <details className="surface email-notification-settings">
        <summary><Mail size={18}/><strong>E-poštna obvestila</strong><span>{settings ? settings.enabled ? settings.transport_ready ? 'Vključena' : 'Čaka na nastavitev pošiljanja' : 'Izključena' : 'Nastavitve'}</span></summary>
        <p>Prejemajte spremembe pogojev in rokov pri razpisih, ki jih spremljate. Nastavitev velja za skupni profil podjetja.</p>
        {error && <p role="alert" className="error-banner">{error}{!settings && <button className="button small" onClick={() => setRevision(old => old + 1)}>Poskusi znova</button>}</p>}
        {!settings && !error && <p role="status"><LoaderCircle size={16} className="spin"/> Nalagamo nastavitve …</p>}
        {settings && <form onSubmit={save}>
            <p className="section-help">Način pošiljanja: {settings.provider === 'resend' ? 'Resend' : settings.provider === 'smtp' ? 'SMTP' : 'Ni nastavljen'}.</p>
            <label className="field"><span>E-poštni naslov prejemnika</span><input type="email" autoComplete="email" maxLength={254} required={enabled} value={email} disabled={busy} onChange={e => { setEmail(e.target.value); setMessage(''); }} placeholder="ime@podjetje.si"/></label>
            <label className="checkbox-row"><input type="checkbox" checked={enabled} disabled={busy} onChange={e => { setEnabled(e.target.checked); setMessage(''); }}/><span>Pošiljaj e-poštna obvestila o spremembah spremljanih razpisov</span></label>
            {!settings.transport_ready && <p className="info-box">Pošiljanje e-pošte na strežniku še ni nastavljeno. Prejemnika lahko shranite že zdaj; obvestila v aplikaciji ostajajo na voljo.</p>}
            <p className="section-help">Obvestilo nastane po uspešnem zajemu spremembe na portalu. Ob vključitvi ne pošiljamo starih obvestil. Ob izklopu ali menjavi naslova prekličemo čakajoča sporočila; že poslanih sporočil ni mogoče preklicati.</p>
            {settings.pending > 0 && <p className="section-help">V čakalni vrsti: {settings.pending}.</p>}
            {settings.failed > 0 && <p role="status" className="info-box">Pošiljanje {settings.failed} obvestil ni uspelo po petih poskusih. Preveriti je treba nastavitve pošiljanja.</p>}
            {settings.last_sent_at && <p className="section-help">Zadnje obvestilo predano v pošiljanje: {new Date(settings.last_sent_at).toLocaleString('sl-SI')}.</p>}
            <button className="button primary small" disabled={busy}>{busy ? <LoaderCircle size={16} className="spin"/> : <Save size={16}/>}Shrani nastavitve</button>
            {message && <p role="status">{message}</p>}
        </form>}
    </details>;
}
