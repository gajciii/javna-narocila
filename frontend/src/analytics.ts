import type { PostHog } from 'posthog-js';

/**
 * Product analytics (PostHog EU Cloud), cookieless: persistence is in memory only, so nothing is
 * stored on the device and no consent banner is needed. A visitor is therefore counted anew on
 * every full page load; within one load (the app is a single page) events and the session replay
 * stay connected. Without VITE_POSTHOG_KEY at build time analytics is off.
 *
 * The SDK is loaded as a separate chunk after start-up so it does not delay the first render;
 * events tracked before it arrives are queued.
 */
const key = import.meta.env.VITE_POSTHOG_KEY;
const host = import.meta.env.VITE_POSTHOG_HOST || 'https://eu.i.posthog.com';
let client: PostHog | null = null;
let started = false;
const queue: [string, Record<string, unknown> | undefined][] = [];

/** Route without ids, e.g. "/razpisi/:id", so pages group in reports. */
function route() {
    const path = window.location.hash.slice(1).split('?')[0] || '/';
    return path.replace(/^(\/razpisi\/)[^/]+/, '$1:id');
}

function changed() {
    if (!client) return;
    // The administration holds staff sessions and database exports, so it is never recorded.
    if (window.location.hash.startsWith('#/administracija')) client.stopSessionRecording();
    else if (!client.sessionRecordingStarted()) client.startSessionRecording();
    // Hash routes (#/razpisi/...) never reload the page, so each route change is a pageview.
    client.capture('$pageview', { $current_url: window.location.href, route: route() });
}

export function initAnalytics() {
    if (!key || started) return;
    started = true;
    import('posthog-js').then(({ default: posthog }) => {
        posthog.init(key, {
            api_host: host,
            persistence: 'memory',
            person_profiles: 'identified_only',
            autocapture: true,
            capture_pageview: false,
            capture_pageleave: true,
            session_recording: { maskAllInputs: true },
        });
        client = posthog;
        changed();
        window.addEventListener('hashchange', changed);
        for (const [event, properties] of queue.splice(0)) posthog.capture(event, properties);
    }).catch(() => { started = false; queue.length = 0; });  // Blocked by an ad blocker: the app works as before.
}

export function track(event: string, properties?: Record<string, unknown>) {
    if (client) client.capture(event, properties);
    else if (started && queue.length < 50) queue.push([event, properties]);
}
