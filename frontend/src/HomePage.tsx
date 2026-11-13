import { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowRight, ArrowUpRight, Pause, Play, Radar } from 'lucide-react';
import './home.css';

const navigation = [
    { label: 'Prijava', href: '#/prijava' },
    { label: 'Registracija', href: '#/registracija' },
    { label: 'Razpisi', href: '#/razpisi' },
    { label: 'AI pomočnik', href: '#/svetovalec' },
    { label: 'Obvestila', href: '#/obvestila' },
    { label: 'Profil podjetja', href: '#/profil' },
];
const steps = [
    { title: 'Najdite pravo priložnost.', description: 'Filtrirajte razpise glede na dejavnost in potrebe svojega podjetja.', href: '#/razpisi', action: 'Razišči razpise' },
    { title: 'Preverite pogoje.', description: 'Poglejte, kaj izpolnjujete, kaj manjka in kje je dokaz v dokumentaciji.', href: '#/svetovalec', action: 'Vprašaj pomočnika' },
    { title: 'Bodite na tekočem.', description: 'Spremljajte nove objave, popravke in spremembe rokov na enem mestu.', href: '#/obvestila', action: 'Poglej obvestila' },
];

export default function HomePage() {
    const [paused, setPaused] = useState(false);
    const how = useRef<HTMLElement>(null);
    useEffect(() => {
        const previous = document.title;
        document.title = 'RazpIzi — Razpisi na izi.';
        return () => { document.title = previous; };
    }, []);
    const showHow = () => how.current?.scrollIntoView({
        behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
        block: 'start',
    });
    return <div className="home-page" data-motion={paused ? 'paused' : 'playing'}>
        <a className="home-skip" href="#/" onClick={event => {
            event.preventDefault();
            document.getElementById('home-content')?.focus();
        }}>Preskoči na vsebino</a>
        <section className="home-hero" aria-labelledby="home-title">
            <img className="home-hero-photo" src="/corporate-building.webp" alt="" aria-hidden="true" width="2200" height="2933" fetchPriority="high" />
            <div className="home-hero-shade" aria-hidden="true" />
            <header className="home-header">
                <a className="home-brand" href="#/" aria-label="RazpIzi, domača stran"><Radar size={29} strokeWidth={1.7}/><span>Razp<span>Izi</span></span></a>
                <nav className="home-top-nav" aria-label="Navigacija domače strani">
                    <button type="button" className="home-how-link" onClick={showHow}>Kako deluje</button>
                    <a className="home-open" href="#/razpisi">Odpri aplikacijo<ArrowUpRight size={17}/></a>
                </nav>
            </header>
            <main className="home-hero-copy" id="home-content" tabIndex={-1}>
                <p className="home-eyebrow">Javna naročila za vaše podjetje</p>
                <h1 id="home-title"><span>Razpisi</span><span>na izi.</span></h1>
                <a className="home-primary" href="#/razpisi">Poišči svoj razpis<ArrowRight size={19}/></a>
            </main>
            <div className="home-hero-bottom">
                <span className="home-bottom-note">Manj iskanja. Več priložnosti.</span>
                <button type="button" className="home-scroll" onClick={showHow}>Spoznajte RazpIzi<ArrowDown size={17}/></button>
                <button type="button" className="home-motion-toggle" aria-pressed={paused} aria-label={paused ? 'Nadaljuj animacijo ozadja' : 'Ustavi animacijo ozadja'} onClick={() => setPaused(value => !value)}>{paused ? <Play size={15}/> : <Pause size={15}/>}<span>{paused ? 'Nadaljuj gibanje' : 'Ustavi gibanje'}</span></button>
            </div>
        </section>
        <nav className="home-navigation" aria-label="Raziščite aplikacijo">{navigation.map((item, index) => <a key={item.href} href={item.href}><span className="home-nav-number">0{index + 1}</span><span>{item.label}</span><ArrowUpRight size={18}/></a>)}</nav>
        <section ref={how} className="home-how" aria-labelledby="home-how-title">
            <div className="home-section-heading"><span className="home-section-label">Kako deluje</span><h2 id="home-how-title">Od objave<br/>do odločitve.</h2></div>
            <div className="home-steps">{steps.map((step, index) => <article className="home-step" key={step.href}>
                <span className="home-step-number">0{index + 1}</span>
                <div><h3>{step.title}</h3><p>{step.description}</p><a href={step.href}>{step.action}<ArrowUpRight size={16}/></a></div>
            </article>)}</div>
        </section>
        <footer className="home-footer"><a href="#/" className="home-footer-brand">RazpIzi<span>Razpisi na izi.</span></a><a href="#/razpisi">Vaša naslednja priložnost<ArrowRight size={18}/></a></footer>
    </div>;
}
