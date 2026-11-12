import { QueryClient } from '@tanstack/react-query';

/**
 * Shared cache for expensive GET requests. Data stays fresh for five minutes,
 * so moving between tenders, tabs and the list reuses earlier responses.
 * Mutations invalidate the affected keys (see `refresh` in App.tsx).
 */
export const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            staleTime: 5 * 60_000,
            gcTime: 30 * 60_000,
            refetchOnWindowFocus: false,
            retry: false,
        },
    },
});

export const queryKeys = {
    bootstrap: ['bootstrap'] as const,
    tenders: (query: string) => ['tenders', query] as const,
    tender: (id: string) => ['tender', id] as const,
    similarAwards: (tenderId: string) => ['similar-awards', tenderId] as const,
    tenderFaq: (tenderId: string) => ['tender-faq', tenderId] as const,
    buyerHistory: (tenderId: string, query: string) => ['buyer-history', tenderId, query] as const,
    tenderPartners: (tenderId: string, companyId: string) => ['tender-partners', tenderId, companyId] as const,
    attachmentOpportunities: (tenderId: string, revision: string) => ['attachment-opportunities', tenderId, revision] as const,
    certifications: ['certifications'] as const,
};
