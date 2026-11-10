export type MatchLevel = 'high' | 'medium' | 'low';
export type ConditionState = 'met' | 'unmet' | 'unknown';
export interface CompanyReference {
    id: string;
    title: string;
    description: string;
    domain: string;
    value: number | null;
    year: number | null;
    confirmed: boolean;
}
export interface Profile {
    id: number;
    name: string;
    registration_number: string;
    activity: string;
    address: string;
    website: string;
    description: string;
    expertise: string[];
    technologies: string[];
    keywords: string[];
    excluded_keywords: string[];
    regions: string[];
    min_value: number | null;
    max_value: number | null;
    available_from: string;
    staff_count: number | null;
    certifications: string[];
    capacity: string;
    source: 'demo' | 'user';
    references: CompanyReference[];
    updated_at?: string;
}
export interface Condition {
    id: string;
    title: string;
    company_value: string;
    status: ConditionState;
    document_id: string | null;
    page: number | null;
    quote: string;
}
export interface TenderDocument {
    id: string;
    title: string;
    url: string;
    pages: number;
    status: 'processed' | 'unprocessed';
    version: number;
    analysis_mode?: string;
    error?: string;
}
export interface Tender {
    id: string;
    title: string;
    buyer: string;
    region: string;
    kind: 'services' | 'goods' | 'works';
    cpv: string[];
    value: number | null;
    published_at: string | null;
    deadline: string | null;
    status: 'open' | 'closed' | 'cancelled' | 'unconfirmed';
    source_type: 'demo' | 'real';
    source_url: string | null;
    source_metadata?: { notice_number?: string; fetched_at?: string; attachment_url?: string; phase?: string; correction_description?: string };
    summary: string;
    description?: string;
    topics: string[];
    technologies: string[];
    following: boolean;
    is_new: boolean;
    has_update: boolean;
    version: number;
    match: {
        level: MatchLevel;
        score: number;
        recommendation: 'recommended' | 'review' | 'unsuitable' | 'closed';
        reasons: string[];
        open_question: string;
        conditions: Condition[];
    };
    criteria: {
        title: string;
        weight: number | null;
    }[];
    documents: TenderDocument[];
    lots: {
        id: string;
        title: string;
        match_level: MatchLevel;
        summary: string;
    }[];
    changes: {
        field: string;
        before: string;
        after: string;
        impact: string;
        document_id?: string;
        page?: number;
    }[];
}
export interface Notification {
    id: number;
    tender_id: string;
    type: 'new' | 'correction' | 'deadline';
    title: string;
    body: string;
    read: boolean;
    created_at: string;
    is_demo: boolean;
}
export interface Filters {
    q?: string;
    exclude?: string;
    cpv?: string[];
    kinds?: string[];
    buyers?: string[];
    regions?: string[];
    min_value?: number;
    max_value?: number;
    published_from?: string;
    published_to?: string;
    deadline_from?: string;
    deadline_to?: string;
    min_days?: number;
    levels?: string[];
    condition_states?: string[];
    include_unknown?: boolean;
    only_new?: boolean;
    only_updates?: boolean;
    only_following?: boolean;
    statuses?: string[];
    source_types?: string[];
    view?: 'recommended' | 'all' | 'following';
    sort?: 'match' | 'deadline' | 'newest' | 'value';
}
export interface SavedSearch {
    id: number;
    name: string;
    filters: Filters;
}
export interface Bootstrap {
    profile: Profile;
    tenders: Tender[];
    notifications: Notification[];
    saved_searches: SavedSearch[];
    meta: {
        demo: boolean;
        ai_mode: 'demo' | 'live';
        today: string;
        last_sync: string | null;
        integrations?: { pjn: { state: string; last_success: string | null; runs_remaining: number; real_count: number }; bizi: { state: string; message: string; url: string } };
    };
}
export interface Citation {
    tender_id: string;
    title: string;
    document_id?: string;
    page?: number;
    quote?: string;
}
export interface ChatResponse {
    answer: string;
    mode: 'demo' | 'live';
    citations: Citation[];
    profile_patch?: Partial<Profile>;
    filters?: Filters;
    warning?: string;
}
export interface ChatMessage extends Partial<ChatResponse> {
    role: 'user' | 'assistant';
    content: string;
    id: string;
    applied?: boolean;
}
