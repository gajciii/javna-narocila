import { useState } from 'react';
import { ExternalLink } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { api } from './api';

type AnnualReport = {
    registration_number?: string;
    state: 'missing_company' | 'not_configured' | 'not_found' | 'unavailable' | 'available';
    source_url: string;
    jolp_url: string;
    report: { year: number; period_start: string | null; period_end: string | null; published_at: string | null;
        net_sales: number | null; assets: number | null; equity: number | null; average_employees: number | null } | null;
};

type ErarPayments = {
    registration_number: string;
    payments: { amount: number; count: number; first_payment_on: string; latest_payment_on: string;
        latest_export_on: string } | null;
};

function registrationId(registrationNumber: string) {
    const id = registrationNumber.replace(/\s/g, '');
    return /^\d{7}$/.test(id) ? `${id}000` : /^\d{10}$/.test(id) ? id : null;
}

export function erarRecipient(registrationNumber: string) {
    const id = registrationId(registrationNumber);
    return id && `https://erar.si/podjetje/${id}/profil/transakcije`;
}

const euro = new Intl.NumberFormat('sl-SI', { style: 'currency', currency: 'EUR' });
const decimal = new Intl.NumberFormat('sl-SI', { maximumFractionDigits: 2 });
const amount = (value: number | null) => value === null ? 'Ni podatka' : euro.format(value);
const displayDate = (value: string | null) => value && Number.isFinite(Date.parse(value))
    ? new Date(value).toLocaleDateString('sl-SI', { timeZone: 'UTC' }) : 'Ni podatka';

export default function CompanyDataSources({ profileId, registrationNumber }: { profileId: number; registrationNumber: string }) {
    const [requested, setRequested] = useState(false);
    const [open, setOpen] = useState(false);
    const id = registrationId(registrationNumber);
    const erar = erarRecipient(registrationNumber);
    const query = useQuery({ queryKey: ['profile-annual-report', profileId, registrationNumber],
        queryFn: ({ signal }) => api<AnnualReport>(`/profiles/${profileId}/annual-report`, { signal }),
        enabled: requested && !!id, retry: false, staleTime: 60_000 });
    const paymentsQuery = useQuery({ queryKey: ['profile-erar-payments', profileId, registrationNumber],
        queryFn: ({ signal }) => api<ErarPayments>(`/profiles/${profileId}/erar-payments`, { signal }),
        enabled: open && !!id, retry: false, staleTime: 60_000 });
    const payments = paymentsQuery.data?.registration_number === id ? paymentsQuery.data.payments : null;
    const report = query.data?.registration_number === id ? query.data.report : null;
    const jolp = id ? `https://www.ajpes.si/jolp/podjetje.asp?maticna=${id}` : 'https://www.ajpes.si/JOLP/default.asp';
    return <details className="quiet-disclosure profile-source" onToggle={event => setOpen(event.currentTarget.open)}>
        <summary>Poslovni register, letna poročila in javna plačila</summary>
        <div className="source-card">
            <p>V poslovnem registru preverite glavno dejavnost in objavljene zastopnike. Za iskanje uporabite matično številko podjetja.</p>
            <a href="https://www.ajpes.si/prs/Default.asp" target="_blank" rel="noreferrer">Odpri poslovni register<ExternalLink size={13}/></a>
            <a href={jolp} target="_blank" rel="noreferrer">Odpri javno objavo letnih poročil (JOLP)<ExternalLink size={13}/></a>
            <p>Letno povprečje zaposlenih iz JOLP lahko vnesete v zavihku Ekipa in certifikati.</p>
            {erar && <a href={erar} target="_blank" rel="noreferrer">Javna plačila podjetju v ERAR<ExternalLink size={13}/></a>}
            {payments && <>
                <h4>Javna plačila podjetju iz uvoženih izvozov ERAR</h4>
                <p>{amount(payments.amount)} · {decimal.format(payments.count)} transakcij</p>
                <small>Plačila od {displayDate(payments.first_payment_on)} do {displayDate(payments.latest_payment_on)} · zadnji izvoz {displayDate(payments.latest_export_on)}</small>
            </>}
            {paymentsQuery.data && !payments && <p>Za to podjetje v uvoženih izvozih ERAR ni plačil.</p>}
            {paymentsQuery.isError && <p role="status">Uvoženih plačil trenutno ni mogoče prikazati.</p>}
            {erar ? <button type="button" className="button small" disabled={query.isFetching} onClick={() => {
                if (requested) void query.refetch(); else setRequested(true);
            }}>{query.isFetching ? 'Pridobivam poročilo …' : 'Prikaži zadnje letno poročilo'}</button>
                : <p>Shranite veljavno matično številko za prikaz podatkov podjetja.</p>}
            {query.isError && <p role="status">Pridobivanje poročila ni uspelo.</p>}
            {query.data?.state === 'not_configured' && <p>Za samodejni prikaz nastavite ključ AJPES LP API. Poročilo lahko poiščete tudi v JOLP.</p>}
            {query.data?.state === 'unavailable' && <p>Podatkov iz AJPES LP API trenutno ni mogoče pridobiti. Poročilo poiščite v JOLP.</p>}
            {query.data?.state === 'not_found' && <p>LP API za to matično številko ni vrnil strukturiranega letnega poročila.</p>}
            {report && <>
                <h4>Letno poročilo {report.year}</h4>
                <p>Obdobje {displayDate(report.period_start)} – {displayDate(report.period_end)} · objavljeno {displayDate(report.published_at)}</p>
                <dl>
                    <dt>Čisti prihodki od prodaje</dt><dd>{amount(report.net_sales)}</dd>
                    <dt>Sredstva</dt><dd>{amount(report.assets)}</dd>
                    <dt>Kapital</dt><dd>{amount(report.equity)}</dd>
                    <dt>Povprečno število zaposlenih po delovnih urah</dt>
                    <dd>{report.average_employees == null ? 'Ni podatka' : decimal.format(report.average_employees)}</dd>
                </dl>
                <a href={query.data?.source_url} target="_blank" rel="noreferrer">Vir · AJPES LP API<ExternalLink size={13}/></a>
            </>}
        </div>
    </details>;
}
