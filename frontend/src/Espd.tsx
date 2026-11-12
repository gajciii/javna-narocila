import { Fragment, useEffect, useMemo, useState, type ChangeEvent, type ReactNode } from 'react';
import { AlertCircle, CheckCircle2, CircleHelp, Download, ExternalLink, FileText, LoaderCircle, Plus, Printer, RotateCcw, Save, ShieldAlert, Trash2 } from 'lucide-react';
import { api } from './api';
import type { Espd, EspdAnswers, EspdRow, EspdSource } from './types';

const sourceLabels: Record<EspdSource, [string, string]> = {
    ajpes: ['AJPES', 'green'], profile: ['Profil', 'neutral'], demo: ['Demo profil', 'amber'], missing: ['Ni podatka', 'amber'],
};
const statusLabels: Record<string, [string, string]> = { met: ['Izpolnjen po profilu', 'green'], unmet: ['Ni izpolnjen', 'red'], unknown: ['Potrebno preveriti', 'amber'] };
const kindLabels: Record<string, string> = { services: 'Storitve', goods: 'Blago', works: 'Gradnje' };
const fmtDate = (value?: string | null) => value && !Number.isNaN(new Date(value).getTime()) ? new Date(value).toLocaleDateString('sl-SI', { timeZone: 'Europe/Ljubljana', day: 'numeric', month: 'long', year: 'numeric' }) : 'Ni podatka';
const yesNo = (value: boolean | null) => value === null ? 'Ni odgovora' : value ? 'Da' : 'Ne';

function Badge({ tone = 'neutral', children }: { tone?: string; children: ReactNode }) { return <span className={`badge ${tone}`}>{children}</span>; }
function Field({ label, hint, className = '', children }: { label: string; hint?: string; className?: string; children: ReactNode }) {
    return <label className={`field ${className}`}><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>;
}
function YesNo({ name, value, onChange, labels = ['Ne', 'Da'] }: { name: string; value: boolean | null; onChange: (v: boolean) => void; labels?: [string, string] }) {
    return <div className="espd-choice" role="radiogroup" aria-label={name}>
        {[false, true].map(option => <label key={String(option)} className={value === option ? 'on' : ''}><input type="radio" name={name} checked={value === option} onChange={() => onChange(option)}/>{labels[Number(option)]}</label>)}
    </div>;
}

export default function EspdPanel({ tenderId, notify }: { tenderId: string; notify: (message: string, error?: boolean) => void }) {
    const [espd, setEspd] = useState<Espd | null>(null);
    const [answers, setAnswers] = useState<EspdAnswers | null>(null);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState('');
    const [dirty, setDirty] = useState(false);
    const [bulkConfirm, setBulkConfirm] = useState(false);

    const load = (data: Espd) => { setEspd(data); setAnswers(data.answers); setDirty(false); };
    useEffect(() => { let active = true; api<Espd>(`/tenders/${encodeURIComponent(tenderId)}/espd`).then(d => active && load(d)).catch(e => active && setError(e.message)); return () => { active = false; }; }, [tenderId]);
    useEffect(() => {
        if (!dirty) return;
        const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
        window.addEventListener('beforeunload', warn);
        return () => window.removeEventListener('beforeunload', warn);
    }, [dirty]);

    const rows = useMemo(() => (espd?.part4 || []).map(row => {
        const override = answers?.selection.responses[row.id];
        return { ...row, response: override ?? row.suggestion, edited: override !== undefined && override !== row.suggestion };
    }), [espd, answers]);

    if (error) return <section className="surface detail-section"><div className="info-box"><AlertCircle size={17}/><p>{error}</p></div></section>;
    if (!espd || !answers) return <section className="surface detail-section espd-loading"><LoaderCircle className="spin" size={22}/><p>Pripravljamo ESPD …</p></section>;

    const update = (fn: (draft: EspdAnswers) => void) => { const next = structuredClone(answers); fn(next); setAnswers(next); setDirty(true); };
    const run = async (kind: string, callback: () => Promise<void>) => { setBusy(kind); try { await callback(); } catch (e) { notify((e as Error).message, true); } finally { setBusy(''); } };
    const save = () => run('save', async () => { load(await api<Espd>(`/tenders/${encodeURIComponent(tenderId)}/espd`, { method: 'PUT', body: JSON.stringify(answers) })); notify('ESPD osnutek je shranjen.'); });
    const reset = () => { if (!window.confirm('Izbrišem shranjen osnutek ESPD za ta razpis? Podatki o podjetju za druge razpise ostanejo.')) return; run('reset', async () => { await api(`/tenders/${encodeURIComponent(tenderId)}/espd`, { method: 'DELETE' }); load(await api<Espd>(`/tenders/${encodeURIComponent(tenderId)}/espd`)); notify('Osnutek ESPD je ponastavljen.'); }); };
    const exportJson = () => {
        const blob = new Blob([JSON.stringify({ format: 'razpisni-radar-espd', version: 1, exported_at: new Date().toISOString(), part1: espd.part1, part2: espd.part2, part4: rows, answers }, null, 2)], { type: 'application/json' });
        const link = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: `espd-${tenderId}.json` });
        link.click(); URL.revokeObjectURL(link.href);
    };
    const print = () => { document.body.classList.add('printing-espd'); const done = () => { document.body.classList.remove('printing-espd'); window.removeEventListener('afterprint', done); }; window.addEventListener('afterprint', done); window.print(); };

    const allCodes = espd.part3.flatMap(g => g.items.map(i => i.code));
    const unanswered = allCodes.filter(code => !answers.exclusion[code]?.answer);
    const operatorField = (key: 'vat_id' | 'contact_name' | 'email' | 'phone') => (e: ChangeEvent<HTMLInputElement>) => update(d => { d.operator[key] = e.target.value; });
    const percent = espd.progress.total ? Math.round(espd.progress.done / espd.progress.total * 100) : 0;

    return <div className="espd">
        <section className="surface detail-section espd-intro">
            <div className="section-heading"><div><h2><FileText size={19}/>ESPD obrazec</h2><p className="section-help">Enotni evropski dokument v zvezi z oddajo javnega naročila. Podatki o naročilu, podjetju in pogojih so predizpolnjeni iz preverjenih virov; izjave o razlogih za izključitev potrdite sami.</p></div><Badge tone={percent === 100 ? 'green' : 'amber'}>{espd.progress.done}/{espd.progress.total} izpolnjeno</Badge></div>
            <div className="progress-track"><span style={{ width: `${percent}%` }}/></div>
            {espd.warnings.map(w => <div className="info-box" key={w}><AlertCircle size={17}/><p>{w}</p></div>)}
            {espd.progress.missing.length > 0 && <details className="quiet-disclosure"><summary>Kaj še manjka ({espd.progress.missing.length})</summary><ul className="espd-missing">{espd.progress.missing.map(m => <li key={m}>{m}</li>)}</ul></details>}
            <div className="espd-actions">
                <button className="button primary small" disabled={!!busy || !dirty} onClick={save}>{busy === 'save' ? <LoaderCircle className="spin" size={15}/> : <Save size={15}/>}{dirty ? 'Shrani osnutek' : 'Shranjeno'}</button>
                <button className="button small" onClick={print}><Printer size={15}/>Natisni / PDF</button>
                <button className="button small" onClick={exportJson}><Download size={15}/>Izvozi JSON</button>
                {espd.updated_at && <button className="button ghost small" disabled={!!busy} onClick={reset}><RotateCcw size={15}/>Ponastavi</button>}
                {espd.updated_at && <small className="muted">Shranjeno {fmtDate(espd.updated_at)}</small>}
            </div>
        </section>

        <section className="surface detail-section">
            <div className="section-heading"><h2><span className="step-number">I</span>Informacije o postopku in naročniku</h2><Badge tone={espd.part1.source_type === 'real' ? 'green' : 'amber'}>{espd.part1.source_type === 'real' ? 'e-Naročanje' : 'Demo razpis'}</Badge></div>
            <dl className="espd-facts">
                <dt>Naročnik</dt><dd>{espd.part1.buyer || 'Ni podatka'}</dd>
                <dt>Naziv naročila</dt><dd>{espd.part1.title}</dd>
                <dt>Številka objave</dt><dd>{espd.part1.notice_number || 'Ni podatka'}{espd.part1.source_url && <a href={espd.part1.source_url} target="_blank" rel="noreferrer"> Izvorna objava<ExternalLink size={12}/></a>}</dd>
                <dt>Vrsta</dt><dd>{kindLabels[espd.part1.kind] || 'Ni podatka'}</dd>
                <dt>CPV</dt><dd>{espd.part1.cpv.join(', ') || 'Ni podatka'}</dd>
                <dt>Rok za oddajo</dt><dd>{fmtDate(espd.part1.deadline)}</dd>
            </dl>
        </section>

        <section className="surface detail-section">
            <div className="section-heading"><h2><span className="step-number">II</span>Informacije o gospodarskem subjektu</h2>{espd.registry && <small className="muted">{espd.registry.attribution}</small>}</div>
            <dl className="espd-facts">{espd.part2.map(f => <Fragment key={f.key}><dt>{f.label}</dt><dd>{f.value || 'Ni podatka'} <Badge tone={sourceLabels[f.source][1]}>{sourceLabels[f.source][0]}</Badge></dd></Fragment>)}</dl>
            <p className="section-help">Naziv, matično številko in naslov spremenite v profilu podjetja.</p>
            <div className="form-grid">
                <Field label="ID za DDV" hint="Na primer SI12345678."><input value={answers.operator.vat_id} onChange={operatorField('vat_id')} placeholder="SI"/></Field>
                <Field label="Velikost podjetja"><select value={answers.operator.size} onChange={e => update(d => { d.operator.size = e.target.value; })}><option value="">Izberite</option>{Object.entries(espd.sizes).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
                <Field label="Kontaktna oseba"><input value={answers.operator.contact_name} onChange={operatorField('contact_name')}/></Field>
                <Field label="E-pošta"><input type="email" value={answers.operator.email} onChange={operatorField('email')}/></Field>
                <Field label="Telefon"><input value={answers.operator.phone} onChange={operatorField('phone')}/></Field>
            </div>
            <div className="espd-subsection"><strong>Zastopniki gospodarskega subjekta</strong>
                {answers.operator.representatives.map((rep, i) => <div className="espd-rep" key={i}>
                    <input aria-label={`Ime zastopnika ${i + 1}`} placeholder="Ime in priimek" value={rep.name} onChange={e => update(d => { d.operator.representatives[i].name = e.target.value; })}/>
                    <input aria-label={`Funkcija zastopnika ${i + 1}`} placeholder="Funkcija" value={rep.role} onChange={e => update(d => { d.operator.representatives[i].role = e.target.value; })}/>
                    <button className="icon-button danger-hover" aria-label={`Odstrani zastopnika ${i + 1}`} onClick={() => update(d => { d.operator.representatives.splice(i, 1); })}><Trash2 size={15}/></button>
                </div>)}
                {answers.operator.representatives.length < 10 && <button className="button small" onClick={() => update(d => { d.operator.representatives.push({ name: '', role: '' }); })}><Plus size={14}/>Dodaj zastopnika</button>}
            </div>
            {espd.part1.lots.length > 0 && <div className="espd-subsection"><strong>Sklopi, za katere oddajate ponudbo</strong>{espd.part1.lots.map(lot => <label className="checkbox-row" key={lot.id}><input type="checkbox" checked={answers.participation.lots.includes(lot.id)} onChange={e => update(d => { d.participation.lots = e.target.checked ? [...d.participation.lots, lot.id] : d.participation.lots.filter(x => x !== lot.id); })}/><span>{lot.title}</span></label>)}</div>}
            {([['joint_bid', 'joint_partners', 'Ali gospodarski subjekt sodeluje v postopku skupaj z drugimi (skupna ponudba)?', 'Navedite partnerje v skupni ponudbi in njihove vloge'],
               ['relies_on_others', 'other_entities', 'Ali se gospodarski subjekt sklicuje na zmogljivosti drugih subjektov?', 'Navedite subjekte in zmogljivosti, na katere se sklicujete'],
               ['subcontracting', 'subcontractors', 'Ali namerava gospodarski subjekt del naročila oddati podizvajalcem?', 'Navedite podizvajalce in delež naročila']] as const).map(([flag, text, question, hint]) =>
                <div className="espd-question" key={flag}><p>{question}</p><YesNo name={question} value={answers.participation[flag]} onChange={v => update(d => { d.participation[flag] = v; })}/>
                    {answers.participation[flag] && <textarea rows={2} aria-label={hint} placeholder={hint} value={answers.participation[text]} onChange={e => update(d => { d.participation[text] = e.target.value; })}/>}</div>)}
            {answers.participation.relies_on_others && <p className="section-help">Za vsak subjekt, na katerega se sklicujete, je potreben ločen ESPD.</p>}
        </section>

        <section className="surface detail-section">
            <div className="section-heading"><div><h2><span className="step-number">III</span>Razlogi za izključitev</h2><p className="section-help">To so izjave pod kazensko in materialno odgovornostjo. Aplikacija jih ne izpolni namesto vas.</p></div><Badge tone={unanswered.length ? 'amber' : 'green'}>{allCodes.length - unanswered.length}/{allCodes.length}</Badge></div>
            {unanswered.length > 0 && <div className="espd-bulk"><label className="checkbox-row"><input type="checkbox" checked={bulkConfirm} onChange={e => setBulkConfirm(e.target.checked)}/><span>Preveril(-a) sem vse spodaj navedene razloge in izjavljam, da pri nobenem neodgovorjenem razlogu za podjetje ne obstaja okoliščina za izključitev.</span></label><button className="button small" disabled={!bulkConfirm} onClick={() => { update(d => { unanswered.forEach(code => { d.exclusion[code] = { answer: 'no', details: '' }; }); }); setBulkConfirm(false); }}><ShieldAlert size={14}/>Odgovori »Ne« pri {unanswered.length} neodgovorjenih</button></div>}
            {espd.part3.map(group => <div className="espd-group" key={group.code}><h3>{group.code}. {group.title}</h3>
                {group.items.map(item => { const value = answers.exclusion[item.code]; return <div className="espd-question" key={item.code}><p>{item.label}</p>
                    <YesNo name={item.label} value={value?.answer ? value.answer === 'yes' : null} onChange={v => update(d => { d.exclusion[item.code] = { answer: v ? 'yes' : 'no', details: d.exclusion[item.code]?.details || '' }; })}/>
                    {value?.answer === 'yes' && <textarea rows={2} aria-label={`Pojasnilo: ${item.label}`} placeholder="Opišite okoliščine in ukrepe za dokazovanje zanesljivosti (samoočiščenje)" value={value.details} onChange={e => update(d => { d.exclusion[item.code].details = e.target.value; })}/>}
                </div>; })}</div>)}
        </section>

        <section className="surface detail-section">
            <div className="section-heading"><div><h2><span className="step-number">IV</span>Pogoji za sodelovanje</h2><p className="section-help">Pogoji iz dokumentacije s predlaganimi odgovori iz vašega profila. Odgovore lahko uredite.</p></div></div>
            <div className="espd-question"><p>α: Splošna navedba – ali gospodarski subjekt izpolnjuje vse zahtevane pogoje za sodelovanje?</p><YesNo name="Splošna navedba" value={answers.selection.global_yes} onChange={v => update(d => { d.selection.global_yes = v; })}/></div>
            {rows.length ? rows.map((row: EspdRow) => <div className="espd-row" key={row.id}>
                <div className="espd-row-head"><span className="espd-section-tag">{row.section}</span><strong>{row.requirement}</strong><Badge tone={statusLabels[row.status][1]}>{statusLabels[row.status][0]}</Badge></div>
                <small className="muted">{row.section_label}</small>
                <blockquote>»{row.quote}« <a href={`/api/documents/${row.document_id}#page=${row.page || 1}`} target="_blank" rel="noreferrer">str. {row.page}<ExternalLink size={11}/></a></blockquote>
                <p className="espd-company-value">{row.status === 'met' ? <CheckCircle2 size={14}/> : <CircleHelp size={14}/>}{row.company_value}</p>
                <textarea rows={Math.min(6, Math.max(2, row.response.split('\n').length + 1))} aria-label={`Odgovor: ${row.requirement}`} placeholder="Opišite, kako izpolnjujete pogoj, in navedite dokazila." value={row.response} onChange={e => update(d => { d.selection.responses[row.id] = e.target.value; })}/>
                {row.edited && row.suggestion && <button className="text-link" onClick={() => update(d => { delete d.selection.responses[row.id]; })}><RotateCcw size={12}/>Obnovi predlog iz profila</button>}
            </div>) : <p className="muted">Pogoji še niso analizirani. Odprite zavihek Dokumenti in zaženite analizo.</p>}
        </section>

        <section className="surface detail-section">
            <div className="section-heading"><h2><span className="step-number">VI</span>Sklepne izjave</h2></div>
            <p className="espd-declaration">Spodaj podpisani uradno izjavljam, da so informacije, navedene v delih II–V, točne in pravilne ter da se v celoti zavedam posledic resnega zavajanja. Na zahtevo in brez odlašanja bom predložil(-a) potrdila in druge vrste dokazil, razen kadar jih naročnik lahko pridobi neposredno iz brezplačne nacionalne baze podatkov.</p>
            <div className="form-grid">
                <Field label="Kraj"><input value={answers.final.place} onChange={e => update(d => { d.final.place = e.target.value; })}/></Field>
                <Field label="Datum"><input type="date" value={answers.final.date} onChange={e => update(d => { d.final.date = e.target.value; })}/></Field>
                <Field label="Podpisnik"><input value={answers.final.signatory} onChange={e => update(d => { d.final.signatory = e.target.value; })}/></Field>
                <Field label="Funkcija"><input value={answers.final.role} onChange={e => update(d => { d.final.role = e.target.value; })}/></Field>
            </div>
            <div className="espd-actions"><button className="button primary small" disabled={!!busy || !dirty} onClick={save}>{busy === 'save' ? <LoaderCircle className="spin" size={15}/> : <Save size={15}/>}{dirty ? 'Shrani osnutek' : 'Shranjeno'}</button><button className="button small" onClick={print}><Printer size={15}/>Natisni / PDF</button></div>
        </section>
        <EspdPrint espd={espd} answers={answers} rows={rows}/>
    </div>;
}

function EspdPrint({ espd, answers, rows }: { espd: Espd; answers: EspdAnswers; rows: EspdRow[] }) {
    const p = answers.participation;
    return <article className="espd-print" aria-hidden="true">
        <h1>Enotni evropski dokument v zvezi z oddajo javnega naročila (ESPD)</h1>
        <p className="espd-print-note">Osnutek, pripravljen v aplikaciji Razpisni radar. Pred oddajo preverite vse podatke in obrazec oddajte na način, ki ga določa naročnik.</p>
        <h2>Del I: Informacije o postopku javnega naročanja in naročniku</h2>
        <table><tbody>
            <tr><th>Naročnik</th><td>{espd.part1.buyer}</td></tr>
            <tr><th>Naziv naročila</th><td>{espd.part1.title}</td></tr>
            <tr><th>Številka objave</th><td>{espd.part1.notice_number || '—'}</td></tr>
            <tr><th>CPV</th><td>{espd.part1.cpv.join(', ') || '—'}</td></tr>
        </tbody></table>
        <h2>Del II: Informacije o gospodarskem subjektu</h2>
        <table><tbody>
            {espd.part2.map(f => <tr key={f.key}><th>{f.label}</th><td>{f.value || '—'}</td></tr>)}
            <tr><th>ID za DDV</th><td>{answers.operator.vat_id || '—'}</td></tr>
            <tr><th>Velikost podjetja</th><td>{espd.sizes[answers.operator.size] || '—'}</td></tr>
            <tr><th>Kontaktna oseba</th><td>{[answers.operator.contact_name, answers.operator.email, answers.operator.phone].filter(Boolean).join(', ') || '—'}</td></tr>
            <tr><th>Zastopniki</th><td>{answers.operator.representatives.map(r => [r.name, r.role].filter(Boolean).join(', ')).join('; ') || '—'}</td></tr>
            {espd.part1.lots.length > 0 && <tr><th>Sklopi</th><td>{espd.part1.lots.filter(l => p.lots.includes(l.id)).map(l => l.title).join('; ') || '—'}</td></tr>}
            <tr><th>Skupna ponudba</th><td>{yesNo(p.joint_bid)}{p.joint_bid && p.joint_partners ? `: ${p.joint_partners}` : ''}</td></tr>
            <tr><th>Zmogljivosti drugih subjektov</th><td>{yesNo(p.relies_on_others)}{p.relies_on_others && p.other_entities ? `: ${p.other_entities}` : ''}</td></tr>
            <tr><th>Podizvajalci</th><td>{yesNo(p.subcontracting)}{p.subcontracting && p.subcontractors ? `: ${p.subcontractors}` : ''}</td></tr>
        </tbody></table>
        <h2>Del III: Razlogi za izključitev</h2>
        {espd.part3.map(g => <table key={g.code}><caption>{g.code}. {g.title}</caption><tbody>{g.items.map(i => { const a = answers.exclusion[i.code]; return <tr key={i.code}><th>{i.label}</th><td>{a?.answer === 'yes' ? `Da${a.details ? `: ${a.details}` : ''}` : a?.answer === 'no' ? 'Ne' : 'Ni odgovora'}</td></tr>; })}</tbody></table>)}
        <h2>Del IV: Pogoji za sodelovanje</h2>
        <table><tbody>
            <tr><th>α: Splošna navedba za vse pogoje</th><td>{yesNo(answers.selection.global_yes)}</td></tr>
            {rows.map(r => <tr key={r.id}><th>{r.section}: {r.requirement}<small>Dokumentacija, str. {r.page}: »{r.quote}«</small></th><td className="pre">{r.response || '—'}</td></tr>)}
        </tbody></table>
        <h2>Del VI: Sklepne izjave</h2>
        <p>Spodaj podpisani uradno izjavljam, da so informacije, navedene v delih II–V, točne in pravilne ter da se v celoti zavedam posledic resnega zavajanja.</p>
        <table><tbody>
            <tr><th>Kraj in datum</th><td>{[answers.final.place, answers.final.date && fmtDate(answers.final.date)].filter(Boolean).join(', ') || '—'}</td></tr>
            <tr><th>Podpisnik</th><td>{[answers.final.signatory, answers.final.role].filter(Boolean).join(', ') || '—'}</td></tr>
            <tr><th>Podpis</th><td className="espd-signature"/></tr>
        </tbody></table>
    </article>;
}
