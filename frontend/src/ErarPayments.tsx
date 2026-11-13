import type { ErarPaymentSummary } from './types';

const euro = new Intl.NumberFormat('sl-SI', { style: 'currency', currency: 'EUR' });
const day = (value: string) => new Date(`${value}T00:00:00`).toLocaleDateString('sl-SI');

export default function ErarPayments({ payments, lotTitle }: { payments: ErarPaymentSummary; lotTitle?: string }) {
    return <div className="erar-payment-summary">
        <span>Izplačano po podatkih ERAR{lotTitle ? ` · ${lotTitle}` : ''}</span>
        <strong>{euro.format(payments.amount)}</strong>
        <small>Število transakcij: {payments.count} · Zadnje plačilo: {day(payments.latest_payment_on)} · Izvoz: {day(payments.latest_export_on)}</small>
        <small>Vsota povezanih plačil iz uvoženih podatkov; zaključek vseh plačil ni potrjen.</small>
    </div>;
}
