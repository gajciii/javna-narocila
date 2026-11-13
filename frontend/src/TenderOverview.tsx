import { useQuery } from '@tanstack/react-query';
import { LoaderCircle } from 'lucide-react';
import { api } from './api';

type Overview = { sentences: string[]; mode: 'live' | 'source'; pending: boolean };

export default function TenderOverview({ tenderId, revision }: { tenderId: string; revision: string }) {
    const summary = useQuery<Overview>({
        queryKey: ['tender-overview', tenderId, revision],
        queryFn: ({ signal }) => api<Overview>(`/tenders/${encodeURIComponent(tenderId)}/overview`, { signal }),
        staleTime: 10 * 60_000,
        refetchInterval: query => query.state.data?.pending ? 2000 : false,
    });
    if (summary.isPending) return <p className="section-help" role="status"><LoaderCircle size={16} className="spin"/> Pripravljamo kratek povzetek razpisa …</p>;
    if (!summary.data) return <p className="section-help" role="status">Povzetka trenutno ni mogoče pripraviti. <button className="text-link" onClick={() => void summary.refetch()}>Poskusi znova</button></p>;
    return <div aria-live="polite"><p className="detail-summary">{summary.data.sentences.join(' ')}</p>{summary.data.pending ? <p className="section-help" role="status">Pripravljamo povzetek dokumentacije …</p> : summary.data.mode === 'source' && <p className="section-help">Pregled iz shranjenih podatkov objave.</p>}</div>;
}
