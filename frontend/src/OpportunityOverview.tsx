import { ArrowRight, Bookmark, CalendarDays, CheckCircle2, ChevronRight, CircleHelp, Radar, Sparkles } from 'lucide-react';
import type { Bootstrap, Filters, Tender } from './types';

const recommended = (t: Tender) => !t.ignored && t.status === 'open' && t.match.level !== 'low' && ['recommended', 'review'].includes(t.match.recommendation);

export function OpportunityOverview({ data, onView }: { data: Bootstrap; onView: (filters: Filters) => void }) {
    const opportunities = data.tenders.filter(recommended);
    const ready = opportunities.filter(t => t.match.recommendation === 'recommended').length;
    const review = opportunities.filter(t => t.match.recommendation === 'review').length;
    const following = data.tenders.filter(t => t.following).length;
    return <section className="opportunity-overview" aria-label="Pregled shranjenega nabora razpisov">
        <button className="overview-item overview-featured" onClick={() => onView({ view: 'recommended' })}>
            <span className="overview-icon"><Radar size={22}/></span>
            <span className="overview-copy"><span>Priložnosti za vas</span><strong>{opportunities.length.toString().padStart(2, '0')}</strong><small>{ready} za pregled · {review} za dodatno preverjanje</small></span><ArrowRight size={18}/>
        </button>
        <button className="overview-item" onClick={() => onView({ view: 'following' })}>
            <span className="overview-icon"><Bookmark size={21}/></span>
            <span className="overview-copy"><span>Spremljani razpisi</span><strong>{following.toString().padStart(2, '0')}</strong><small>Vaš ožji izbor na enem mestu</small></span><ArrowRight size={18}/>
        </button>
        <a className="overview-item" href="#/obvestila">
            <span className="overview-icon amber"><CircleHelp size={21}/></span>
            <span className="overview-copy"><span>Nova obvestila</span><strong>{data.notifications.filter(n => !n.read).length.toString().padStart(2, '0')}</strong><small>Spremembe razpisov in predlogi</small></span><ArrowRight size={18}/>
        </a>
    </section>;
}

export function OpportunityAside({ data, goChat }: { data: Bootstrap; goChat: () => void }) {
    const deadlines = data.tenders.filter(t => t.following && t.status === 'open' && t.deadline)
        .sort((a, b) => new Date(a.deadline!).getTime() - new Date(b.deadline!).getTime()).slice(0, 3);
    const incomplete = data.profile.references.filter(r => !r.confirmed || r.value == null || r.year == null).length;
    return <aside className="opportunity-aside" aria-label="Naslednji koraki">
        <section className="assistant-invite">
            <span className="aside-eyebrow"><Sparkles size={16}/>VAŠ RAZPISNI POMOČNIK</span>
            <h2>Od dolgega razpisa<br/>do jasne odločitve.</h2>
            <p>Preverite pogoje, poiščite dokaze ali primerjajte priložnosti za svoje podjetje.</p>
            <button className="button" onClick={goChat}>Vprašaj pomočnika<ArrowRight size={16}/></button>
            <span className="assistant-mode">{data.meta.ai_mode === 'live' ? 'AI je povezan' : 'AI ni povezan · pregled po pravilih'}</span>
        </section>
        <section className="deadline-agenda">
            <div className="aside-heading"><h2>Prihajajoči roki</h2><CalendarDays size={18}/></div>
            <p>Odprti razpisi, ki jih spremljate</p>
            {deadlines.length ? deadlines.map(t => <a key={t.id} className="agenda-item" href={`#/razpisi/${t.id}`}>
                <span className="agenda-date"><strong>{new Date(t.deadline!).toLocaleDateString('sl-SI', { day: '2-digit', timeZone: 'Europe/Ljubljana' }).replace('.', '')}</strong><small>{new Date(t.deadline!).toLocaleDateString('sl-SI', { month: 'short', timeZone: 'Europe/Ljubljana' })}</small></span>
                <span><strong>{t.title}</strong><small>e-Naročanje</small></span><ChevronRight size={16}/>
            </a>) : <div className="agenda-empty"><Bookmark size={20}/><p>Spremljajte razpis in njegov rok se bo prikazal tukaj.</p></div>}
        </section>
        <a className="profile-nudge" href="#/profil"><span>{incomplete ? <CircleHelp size={20}/> : <CheckCircle2 size={20}/>}</span><div><strong>{incomplete ? 'Dopolnite svoje reference' : 'Vaš profil, vaše priložnosti.'}</strong><p>{incomplete ? `Reference z manjkajočimi podatki: ${incomplete}. Dopolnitev omogoča natančnejši pregled pogojev.` : 'Posodobite znanja, ekipo in reference svojega podjetja.'}</p><span>Uredi profil<ArrowRight size={14}/></span></div></a>
        <p className="data-context">Pregled vključuje shranjene objave s portala e-Naročanje. Ujemanje ni zagotovilo za uspešno prijavo.</p>
    </aside>;
}
