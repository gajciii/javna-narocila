import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Plus, Search, X } from 'lucide-react';
import { api } from './api';
import type { CertificationOption } from './types';

export const certificateKey = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim().replace(/iso\s*(?:\/\s*)?iec\s*/g, 'iso ').replace(/[\s-]+/g, '');
const defaults = ['ISO 9001', 'ISO 14001', 'ISO/IEC 27001', 'ISO 45001'].map(label => ({ key: certificateKey(label), label, required: false }));

export default function CertificationSelect({ value, onChange }: { value: string[]; onChange: (value: string[]) => void }) {
    const [options, setOptions] = useState<CertificationOption[]>(defaults);
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState('');
    const [warning, setWarning] = useState(false);
    const root = useRef<HTMLDivElement>(null);
    useEffect(() => { let active = true; api<CertificationOption[]>('/certifications').then(data => { if (active) setOptions(data); }).catch(() => { if (active) setWarning(true); }); return () => { active = false; }; }, []);
    useEffect(() => { const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); }; document.addEventListener('pointerdown', outside); return () => document.removeEventListener('pointerdown', outside); }, []);
    const known = new Map(options.map(option => [option.key, option]));
    value.forEach(label => { const key = certificateKey(label); if (!known.has(key)) known.set(key, { key, label, required: false }); });
    const selected = new Set(value.map(certificateKey));
    const shown = [...known.values()].filter(option => certificateKey(option.label).includes(certificateKey(query)));
    const toggle = (label: string) => { const key = certificateKey(label); onChange(selected.has(key) ? value.filter(v => certificateKey(v) !== key) : [...value, label]); };
    return <div className="cert-select" ref={root} onKeyDown={e => { if (e.key === 'Escape' && open) { e.preventDefault(); e.stopPropagation(); setOpen(false); } }}>
        <div className="cert-selected">{value.map(label => <span className="input-chip" key={label}>{label}<button type="button" aria-label={`Odstrani certifikat ${label}`} onClick={() => onChange(value.filter(v => v !== label))}><X size={13}/></button></span>)}</div>
        <button type="button" className="button cert-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>Izberi certifikate{value.length > 0 && <span>({value.length})</span>}<ChevronDown size={15}/></button>
        {open && <div className="cert-options"><div className="cert-search"><Search size={15}/><input autoFocus aria-label="Poišči certifikat" placeholder="Poišči ali vnesi drug certifikat" value={query} maxLength={150} onChange={e => setQuery(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') e.preventDefault(); }}/></div><div className="cert-option-list">{shown.map(option => <label className="checkbox-row" key={option.key}><input type="checkbox" checked={selected.has(option.key)} onChange={() => toggle(option.label)}/><span>{option.label}{option.required && <small>Zahtevano v vaših razpisih</small>}</span></label>)}</div>{query.trim() && !known.has(certificateKey(query)) && <button type="button" className="text-link" onClick={() => { toggle(query.trim()); setQuery(''); }}><Plus size={14}/>Dodaj drug certifikat: {query.trim()}</button>}{warning && <p className="small-text muted">Zahtev iz razpisov ni bilo mogoče naložiti. Na voljo so osnovne možnosti in vaši vnosi.</p>}</div>}
        <small className="cert-note">Uporabniška navedba. Različico, veljavnost in obseg preverite v dokazilih.</small>
    </div>;
}
