import { useEffect, useState, type FormEvent } from 'react';
import { LoaderCircle, Mail, Save } from 'lucide-react';
import { api } from './api';

type EmailType = 'correction' | 'deadline';
type EmailSettings = {
    provider: 'smtp' | 'resend' | 'unavailable'; enabled: boolean; email: string; account_email: string; types: EmailType[];
    transport_ready: boolean; pending: number; failed: number; last_sent_at: string | null;
};

const TYPES: { value: EmailType; label: string; help: string }[] = [
    { value: 'correction', label: 'Spremembe pogojev in dokumentacije', help: 'Popravki objave, novi dodatki in spremenjeni pogoji pri razpisih, ki jih spremljate.' },
    { value: 'deadline', label: 'Spremembe rokov', help: 'Podaljšan ali skrajšan rok za oddajo ponudb pri razpisih, ki jih spremljate.' },
];

export default function EmailNotificationSettings() {
    const [settings, setSettings] = useState<EmailSettings | null>(null);
    const [email, setEmail] = useState('');
    const [enabled, setEnabled] = useState(false);
    const [types, setTypes] = useState<EmailType[]>([]);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [message, setMessage] = useState('');
    const [revision, setRevision] = useState(0);
    const apply = (value: EmailSettings) => {
        // A new account starts with its login address as the recipient.
        setSettings(value); setEmail(value.email || value.account_email); setEnabled(value.enabled); setTypes(value.types);
    };
    useEffect(() => {
        let active = true;
        setError('');
        api<EmailSettings>('/notifications/email-settings').then(value => { if (active) apply(value); })
            .catch(e => { if (active) setError((e as Error).message); });
        return () => { active = false; };
    }, [revision]);
    const toggleType = (value: EmailType, on: boolean) => {
        setTypes(old => on ? [...old, value] : old.filter(t => t !== value)); setMessage('');
    };
    const save = async (event: FormEvent) => {
        event.preventDefault(); setBusy(true); setError(''); setMessage('');
        try {
            const result = await api<EmailSettings>('/notifications/email-settings', { method: 'PUT', body: JSON.stringify({ email, enabled, types }) });
            apply(result);
            setMessage(result.enabled ? result.transport_ready ? 'Nastavitve so shranjene. Obvestila prejmete za prihodnje spremembe.' : 'Nastavitve so shranjene. Pošiljanje bo na voljo, ko bo nastavljeno na strežniku.' : 'E-poštna obvestila so izključena.');
        } catch (e) { setError((e as Error).message); }
        finally { setBusy(false); }
    };
    return <section className="surface email-notification-settings" aria-labelledby="email-settings-title">
        <h2 id="email-settings-title"><Mail size={18}/>E-poštna obvestila</h2>
        <p>Obvestila veljajo za razpise, ki jih spremljate. V aplikaciji jih vidite v razdelku Obvestila ne glede na te nastavitve.</p>
        {error && <p role="alert" className="error-banner">{error}{!settings && <button className="button small" onClick={() => setRevision(old => old + 1)}>Poskusi znova</button>}</p>}
        {!settings && !error && <p role="status"><LoaderCircle size={16} className="spin"/> Nalagamo nastavitve …</p>}
        {settings && <form onSubmit={save}>
            <label className="checkbox-row"><input type="checkbox" checked={enabled} disabled={busy} onChange={e => { setEnabled(e.target.checked); setMessage(''); }}/><span>Pošiljaj e-poštna obvestila</span></label>
            <label className="field"><span>E-poštni naslov prejemnika</span><input type="email" autoComplete="email" maxLength={254} required={enabled} value={email} disabled={busy} onChange={e => { setEmail(e.target.value); setMessage(''); }} placeholder="ime@podjetje.si"/></label>
            <fieldset className="email-types" disabled={busy || !enabled}>
                <legend>Katera obvestila želite prejemati</legend>
                {TYPES.map(type => <label className="checkbox-row" key={type.value}><input type="checkbox" checked={types.includes(type.value)} onChange={e => toggleType(type.value, e.target.checked)}/><span><strong>{type.label}</strong><small>{type.help}</small></span></label>)}
                {enabled && !types.length && <p className="info-box">Izberite vsaj eno vrsto ali izklopite e-poštna obvestila.</p>}
            </fieldset>
            {!settings.transport_ready && <p className="info-box">Pošiljanje e-pošte na strežniku še ni nastavljeno. Nastavitve lahko shranite že zdaj; obvestila v aplikaciji ostajajo na voljo.</p>}
            <p className="section-help">Ob vključitvi ne pošiljamo starih obvestil. Ob izklopu ali menjavi naslova prekličemo čakajoča sporočila; že poslanih ni mogoče preklicati.</p>
            {settings.pending > 0 && <p className="section-help">V čakalni vrsti: {settings.pending}.</p>}
            {settings.failed > 0 && <p role="status" className="info-box">Pošiljanje {settings.failed} obvestil ni uspelo po petih poskusih. Preveriti je treba nastavitve pošiljanja.</p>}
            {settings.last_sent_at && <p className="section-help">Zadnje obvestilo predano v pošiljanje: {new Date(settings.last_sent_at).toLocaleString('sl-SI')}.</p>}
            <button className="button primary small" disabled={busy || (enabled && !types.length)}>{busy ? <LoaderCircle size={16} className="spin"/> : <Save size={16}/>}Shrani nastavitve</button>
            {message && <p role="status">{message}</p>}
        </form>}
    </section>;
}
