export type MatchLevel = 'high' | 'medium' | 'low';
export type ConditionState = 'met' | 'unmet' | 'unknown';
export interface RegistrySource {
    provider: 'ajpes';
    via: string;
    url: string;
    license: string;
    attribution: string;
    retrieved_at: string;
    dataset_updated_at: string | null;
    name: string;
    registration_number: string;
    address: string;
    legal_form: string;
    registration_authority: string;
}
export interface CompanySearchResult {
    results: { name: string; registration_number: string; address: string; legal_form: string; registration_authority: string }[];
    total: number;
    source: Pick<RegistrySource, 'provider' | 'via' | 'url' | 'license' | 'attribution' | 'retrieved_at' | 'dataset_updated_at'>;
    mode: 'live' | 'cached';
    stale: boolean;
    warning?: string;
}
export interface CompanyReference {
    id: string;
    title: string;
    description: string;
    domain: string;
    value: number | null;
    year: number | null;
    confirmed: boolean;
    project_identifier?: string;
    evidence_source?: string;
    evidence_url?: string;
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
    employment_report?: { average: number | null; year: number | null } | null;
    certifications: string[];
    capacity: string;
    source: 'demo' | 'user';
    registry_source?: RegistrySource;
    references: CompanyReference[];
    /** The company's own answers to tender conditions; reused for similar conditions in other tenders. */
    condition_answers?: ConditionAnswer[];
    updated_at?: string;
}
export interface ConditionAnswer {
    id: string;
    answer: 'met' | 'unmet';
    category: TenderCondition['category'];
    title: string;
    requirement: string;
    tender_id: string;
    tender_title: string;
    updated_at: string;
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
export interface TenderCondition {
    id: string;
    category: 'exclusion' | 'professional' | 'economic' | 'technical' | 'guarantee' | 'other';
    category_label: string;
    title: string;
    requirement: string;
    quote: string;
    document_id: string;
    document_title: string;
    page: number | null;
    locator: string;
    status: ConditionState | 'manual';
    /** Status from the profile data alone, before the company's own answer. */
    auto_status: ConditionState | 'manual';
    company_value: string;
    /** The company's saved answer that applies; inherited when it was given for a similar condition elsewhere. */
    profile_answer: { id: string; answer: 'met' | 'unmet'; tender_id: string; tender_title: string; title: string; inherited: boolean } | null;
}
export interface KeywordMatch {
    term: string;
    /** Tender fields containing the term, e.g. "naslovu", "opisu". */
    fields: string[];
    evidence: { document_id: string; document_title: string; page: number | null; locator: string; quote: string; match_start: number | null; match_end: number | null } | null;
}
export interface ErarPaymentSummary {
    amount: number;
    count: number;
    latest_export_on: string;
    latest_payment_on: string;
}
export interface Tender {
    erar_payments?: (ErarPaymentSummary & { award_id: string; lot_title: string })[];
    id: string;
    tender_conditions?: { mode: 'live' | 'empty' | 'unavailable' | 'pending'; message: string; current?: boolean; items: TenderCondition[] };
    title: string;
    buyer: string;
    region: string;
    kind: 'services' | 'goods' | 'works';
    cpv: string[];
    /** Published estimate in EUR, excluding VAT. */
    value: number | null;
    /** Published contract total in EUR; not the final cost of execution. */
    awarded_value: number | null;
    published_at: string | null;
    deadline: string | null;
    status: 'open' | 'closed' | 'cancelled' | 'unconfirmed';
    source_type: 'demo' | 'real';
    source_url: string | null;
    source_metadata?: { notice_number?: string; fetched_at?: string; attachment_url?: string; submission_url?: string | null; phase?: string; correction_description?: string };
    summary: string;
    description?: string;
    topics: string[];
    technologies: string[];
    following: boolean;
    /** Hidden from the account's lists; shown only in the Skriti view. */
    ignored: boolean;
    is_new: boolean;
    has_update: boolean;
    version: number;
    /** Present in search results and on a detail page opened from a search: every search term found in the tender. */
    keyword_matches?: KeywordMatch[];
    match: {
        level: MatchLevel;
        score: number;
        mode: 'gemini' | 'rules';
        warning?: string | null;
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
    tender_id: string | null;
    type: 'new' | 'correction' | 'deadline' | 'improvement';
    title: string;
    body: string;
    read: boolean;
    created_at: string;
    is_demo: boolean;
    improvement?: ImprovementEvaluation | null;
}
export type ImprovementAction =
    | { kind: 'certification'; certification: string }
    | { kind: 'staff'; minimum: number }
    | { kind: 'technology'; technologies: string[] }
    | { kind: 'reference'; domain: string; minimum_count: number; minimum_value: number | null; max_age_years: number | null }
    | { kind: 'complete_profile'; field: string; domain: string };
export interface ImprovementImpact {
    id: string;
    title: string;
    deadline: string | null;
    status: string;
    source_type: 'real' | 'demo';
    before_recommendation: Tender['match']['recommendation'];
    after_recommendation: Tender['match']['recommendation'];
    newly_recommended: boolean;
    changes: { before: Condition; after: Condition; improved: boolean }[];
    remaining_conditions: Condition[];
    open_question: string;
    documentation_incomplete: boolean;
}
export interface ImprovementEvaluation {
    actions: ImprovementAction[];
    labels: string[];
    source_type: 'demo' | 'real';
    summary: Record<'open' | 'historical', { affected_tenders: number; newly_recommended: number; improved_conditions: number; needs_data: number }>;
    open: ImprovementImpact[];
    historical: ImprovementImpact[];
    evaluated_at: string;
    assumptions: string[];
}
export interface ImprovementPlan {
    id: number;
    name: string;
    actions: ImprovementAction[];
    source_type: 'demo' | 'real';
    evaluation: ImprovementEvaluation;
    created_at: string;
    updated_at: string;
}
export interface Filters {
    q?: string;
    exclude?: string;
    cpv?: string[];
    kinds?: string[];
    buyers?: string[];
    regions?: string[];
    min_score?: number;
    include_partner_opportunities?: boolean;
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
    view?: 'recommended' | 'all' | 'following' | 'ignored';
    sort?: 'match' | 'deadline' | 'newest' | 'value';
}
export interface SavedSearch {
    id: number;
    name: string;
    filters: Filters;
}
/** GET /api/tenders: the filtered page plus tab badges and filter options over all tenders. */
export interface TenderList {
    results: Tender[];
    count: number;
    counts: { recommended: number; all: number; following: number; ignored: number };
    facets: { regions: string[]; buyers: string[] };
    /** AI relevance is still being scored in the background; results use rules until it finishes. */
    relevance_pending: boolean;
}
export interface Bootstrap {
    profiles: Pick<Profile, 'id' | 'name' | 'registration_number'>[];
    profile: Profile;
    notifications: Notification[];
    saved_searches: SavedSearch[];
    meta: {
        demo: boolean;
        ai_mode: 'rules' | 'live';
        today: string;
        last_sync: string | null;
        integrations?: { pjn: { state: string; last_success: string | null; runs_remaining: number; real_count: number }; ajpes: { state: string; last_success: string | null; message: string; url: string } };
    };
}
export interface CapabilityEvidence { source: string; url: string; confirmed: boolean }
export interface Partner {
    id: number;
    source_type: 'real' | 'demo';
    profile: Profile;
    capability_evidence: CapabilityEvidence;
    updated_at: string;
}
/** A tender condition as used in partner comparisons: an extracted condition or a legacy requirement. */
export interface PartnerTenderCondition {
    id: string;
    category: TenderCondition['category'];
    category_label: string;
    title: string;
    requirement: string;
    quote: string;
    document_id: string | null;
    document_title: string;
    page: number | null;
    status: ConditionState | 'manual';
    company_value: string;
    /** Whether the partner can be marked as meeting it (extracted conditions only). */
    answerable: boolean;
}
export interface PartnerConditionAnswer { answer: 'met' | 'unmet'; tender_id: string; tender_title: string; inherited: boolean }
export interface PartnerCondition {
    condition: PartnerTenderCondition;
    partner_condition: { status: ConditionState | 'manual'; company_value: string; answer: PartnerConditionAnswer | null };
    state: 'already_met' | 'potential' | 'unresolved';
    label: string;
    explanation: string;
    evidence: (CapabilityEvidence & { reference_id?: string; title?: string })[];
}
export interface PartnerComparison {
    partner: Partner;
    supported_conditions: number;
    remaining_conditions: number;
    /** Exclusion grounds the partner was marked as not meeting. */
    blocked_by: string[];
    content_score: number;
    content_level: MatchLevel;
    conditions: PartnerCondition[];
    documentation_incomplete: boolean;
    disclaimer: string;
}
export interface PartnerSummary { id: number; name: string; supported_conditions: number; remaining_conditions: number; blocked_by: string[] }
export interface PartnerResults {
    tender_id: string;
    source_type: 'demo' | 'real';
    missing_conditions: PartnerTenderCondition[];
    candidates: PartnerComparison[];
    /** Every partner of the company, best first. */
    partners: PartnerSummary[];
    comparison: PartnerComparison | null;
    message: string;
}
export interface SuggestedPartnerWin {
    award_id: string;
    title: string;
    lot_title: string;
    buyer: string;
    published_on: string | null;
    value: number | null;
    joint: boolean;
    similarity: number;
    notice_url: string;
}
/** A company that won similar public contracts, suggested as a partner. */
export interface SuggestedPartner {
    registration_number: string;
    name: string;
    wins_count: number;
    total_value: number | null;
    latest_win: string | null;
    joint_bids: number;
    wins: SuggestedPartnerWin[];
    /** Set when the company is already one of your partners. */
    partner_id: number | null;
}
export interface PartnerSuggestions { tender_id: string; items: SuggestedPartner[]; message: string; reference_gaps: string[]; source: string }
export interface CertificationOption { key: string; label: string; required: boolean }
export interface WebsiteEvidence {
    url: string;
    quote: string;
    kind: 'text' | 'code' | 'meta';
}
export interface WebsiteSuggestion {
    value: string;
    evidence: WebsiteEvidence[];
}
export interface WebsiteAnalysis {
    url: string;
    final_url: string;
    mode: 'live' | 'heuristic';
    pages: { url: string; title: string }[];
    suggestions: {
        activity: WebsiteSuggestion | null;
        description: WebsiteSuggestion | null;
        expertise: WebsiteSuggestion[];
        technologies: WebsiteSuggestion[];
        keywords: WebsiteSuggestion[];
    };
    /** Registration numbers stated on the site, normalized to 10 digits. */
    registration_numbers: WebsiteSuggestion[];
    warning: string | null;
    message: string;
}
export type EspdSource = 'ajpes' | 'profile' | 'demo' | 'missing';
export interface EspdAnswers {
    operator: { vat_id: string; contact_name: string; email: string; phone: string; size: string; representatives: { name: string; role: string }[] };
    participation: { lots: string[]; joint_bid: boolean | null; joint_partners: string; relies_on_others: boolean | null; other_entities: string; subcontracting: boolean | null; subcontractors: string };
    exclusion: Record<string, { answer: 'no' | 'yes' | null; details: string }>;
    selection: { global_yes: boolean | null; responses: Record<string, string> };
    final: { place: string; date: string; signatory: string; role: string };
}
export interface EspdRow {
    id: string; section: string; section_label: string; kind: string; requirement: string;
    document_id: string; page: number | null; quote: string; status: ConditionState; company_value: string;
    suggestion: string; response: string; edited: boolean; evidence: { type: string; id: string; title: string }[];
}
export interface Espd {
    tender_id: string; tender_status: string;
    part1: { buyer: string; title: string; notice_number: string; source_url: string; cpv: string[]; kind: string; deadline: string | null; lots: { id: string; title: string }[]; source_type: string };
    part2: { key: string; label: string; value: string; source: EspdSource }[];
    registry: { attribution: string; retrieved_at: string } | null;
    part3: { code: string; title: string; items: { code: string; label: string }[] }[];
    part4: EspdRow[];
    answers: EspdAnswers;
    sizes: Record<string, string>;
    progress: { done: number; total: number; missing: string[] };
    warnings: string[];
    updated_at: string | null;
}
export interface PastAwardWinner { name: string; registration_number: string }
export interface PastAwardParticipant extends PastAwardWinner {
    outcome: 'winner' | 'not_selected' | 'unknown'; label: string; source_url: string;
    provenance: 'award_notice' | 'imported_record';
}
export interface PastAward {
    erar_payments?: ErarPaymentSummary | null;
    value_comparison?: { currency: string; estimated: number; contracted: number; difference: number; ratio: number } | null;
    estimate_currency?: string | null;
    award_currency?: string | null;
    participants: PastAwardParticipant[];
    participant_coverage: 'partial_records' | 'winners_only';
    id: string; notice_id: string; notice_url: string; notice_number: string; published_on: string | null; similarity: number;
    title: string; lot_title: string; buyer: string; kind: 'services' | 'goods' | 'works' | null; cpv: string[]; procedure: string;
    framework: boolean; currency: string | null; estimated_value: number | null; awarded_value: number | null;
    lowest_offer: number | null; highest_offer: number | null; tenders_received: number | null; awarded: boolean; winners: PastAwardWinner[];
}
export interface SimilarAwards {
    tender_id: string; mode: 'ai' | 'text' | 'empty'; matching?: 'semantic' | 'text'; message: string; warning: string | null;
    dataset: { label: string; license: string; attribution: string; lots: number; coverage_from: string | null; coverage_to: string | null; imported_at: string | null };
    results: PastAward[];
    summary: {
        count: number; awarded: number; not_awarded: number; median_tenders: number | null; single_bid_share: number | null;
        median_price_to_estimate: number | null; price_to_estimate_count: number; median_offer_spread: number | null; offer_spread_count: number;
        value_totals?: { estimated: number; contracted: number; difference: number; ratio: number; below: number; equal: number; above: number } | null;
        top_winners: (PastAwardWinner & { wins: number })[];
    };
}

export interface BuyerHistory {
    mode: 'data' | 'empty' | 'ambiguous'; message: string;
    buyers: PastAwardWinner[]; buyer_index: number;
    buyer: (PastAwardWinner & { matched_by?: 'registration_number' | 'name' }) | null;
    dataset: SimilarAwards['dataset'];
    summary: {
        lots: number; awarded_lots: number; not_awarded_lots: number; supplier_count: number;
        known_bid_lots: number; single_bid_lots: number; single_bid_share: number | null;
        total_value_eur: number; value_lots: number; joint_lots: number; framework_lots: number;
        excluded_value_lots: number; superseded_lots: number; undated_lots: number;
        coverage_from: string | null; coverage_to: string | null;
    } | null;
    suppliers: (PastAwardWinner & {
        key: string; wins: number; sole_wins: number; joint_wins: number; single_bid_wins: number;
        share: number | null; value_eur: number; value_count: number; value_share: number | null;
    })[];
    signals: { kind: string; text: string }[];
    results: Omit<PastAward, 'similarity'>[]; history_count: number; page: number; page_size: number;
}

export interface TenderFaqItem {
    id: number;
    kind: 'question' | 'clarification';
    question: string;
    answer: string;
    published_at: string | null;
}
export interface TenderFaq {
    available: boolean;
    items: TenderFaqItem[];
    source_url?: string;
    message?: string;
    error?: string;
    warning?: string;
    synced_at?: string | null;
    document_id?: string | null;
}

export interface AwardReferences {
    registration_number: string;
    items: { reference: CompanyReference; buyer: string; published_on: string | null; joint: boolean; added: boolean }[];
    covered_from?: string | null;
    message?: string;
}

export interface ContractParty { name: string; registration_number: string }
export interface SignedContract {
    id: number; title: string; procurement_title: string; buyer: string; buyer_registration: string;
    contractors: ContractParty[]; cpv: string; cpv_label: string; kind: string; framework: boolean; value: number | null;
    concluded_on: string | null; valid_from: string | null; valid_to: string | null; effective_end: string | null;
    extended: boolean; addenda_count: number; days_left: number | null; status: 'active' | 'ended' | 'unknown';
    notice_number: string; procurement_number: string; files: { title: string; url: string }[];
}
export interface ContractDataset {
    attribution: string; contracts: number; with_end: number;
    coverage_from: string | null; coverage_to: string | null; register_synced_until: string | null;
}
export interface Incumbents {
    mode: 'data' | 'empty'; message: string; buyers: string[]; synced_at: string | null; complete: boolean; total?: number;
    headline: { kind: 'active' | 'recent'; cpv_level: number; end: string | null; contractors: (ContractParty & { contracts: number })[] } | null;
    results: (SignedContract & { cpv_level: number })[];
    dataset: ContractDataset;
    refresh: { fetched: number; remaining: number; errors: number; skipped: boolean } | null;
}
export interface ExpectedTenders {
    mode: 'data' | 'empty' | 'profile_missing'; message: string; months: number; terms: string[]; cpv: string;
    results: (SignedContract & { matched_terms: string[]; newer_contract: { id: number; title: string; concluded_on: string | null; contractors: string[] } | null })[];
    count: number; page: number; page_size: number; dataset: ContractDataset;
}
