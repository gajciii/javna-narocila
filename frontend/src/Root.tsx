import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import App from './App';
import HomePage from './HomePage';
import AuthPage, { type AccountSession } from './AuthPage';
import { api, post } from './api';
import { queryClient } from './queryClient';

const sessionKey = ['auth-session'] as const;
export default function Root() {
    const [route, setRoute] = useState(() => window.location.hash.slice(1) || '/');
    const [logoutError, setLogoutError] = useState('');
    const session = useQuery({ queryKey: sessionKey, queryFn: async () => {
        const value = await api<AccountSession>('/auth/session');
        const previous = queryClient.getQueryData<AccountSession>(sessionKey);
        if (previous && previous.user?.id !== value.user?.id) {
            await queryClient.cancelQueries({ predicate: query => query.queryKey[0] !== 'auth-session' });
            queryClient.removeQueries({ predicate: query => query.queryKey[0] !== 'auth-session' });
        }
        return value;
    }, staleTime: 0, refetchOnWindowFocus: 'always', refetchOnReconnect: 'always' });
    useEffect(() => {
        const update = () => { setRoute(window.location.hash.slice(1) || '/'); window.scrollTo(0, 0); };
        const expired = () => {
            void queryClient.cancelQueries().then(() => {
                queryClient.clear();
                queryClient.setQueryData<AccountSession>(sessionKey, { authenticated: false, user: null });
                window.location.hash = '/prijava';
            });
        };
        const changed = () => {
            void queryClient.cancelQueries().then(async () => {
                queryClient.clear();
                const value = await api<AccountSession>('/auth/session');
                queryClient.setQueryData(sessionKey, value);
                if (!value.authenticated) window.location.hash = '/prijava';
            }).catch(() => { window.location.hash = '/prijava'; });
        };
        window.addEventListener('account-session-changed', changed);
        window.addEventListener('hashchange', update);
        window.addEventListener('account-session-expired', expired);
        return () => { window.removeEventListener('account-session-changed', changed); window.removeEventListener('hashchange', update); window.removeEventListener('account-session-expired', expired); };
    }, []);
    const signedIn = async (value: AccountSession) => {
        await queryClient.cancelQueries(); queryClient.clear(); queryClient.setQueryData(sessionKey, value);
        if (route === '/prijava' || route === '/registracija') window.location.hash = '/razpisi';
    };
    const signOut = async () => {
        setLogoutError('');
        try { await post('/auth/logout'); await signedIn({ authenticated: false, user: null }); window.location.hash = '/prijava'; }
        catch (e) { setLogoutError((e as Error).message); }
    };
    if (route === '/' || route === '/domov') return <HomePage/>;
    if (!session.data) return <main className="account-page"><p>{session.error ? 'Povezava s strežnikom ni uspela.' : 'Preverjam prijavo …'}</p>{session.error && <button className="button" onClick={() => void session.refetch()}>Poskusi znova</button>}</main>;
    if (!session.data.authenticated || !session.data.user) return <AuthPage key={route === '/registracija' ? 'register' : 'login'} register={route === '/registracija'} onSuccess={value => void signedIn(value)}/>;
    return <>{logoutError && <div className="error-banner" role="alert">{logoutError}</div>}<App key={session.data.user.id} user={session.data.user} signOut={signOut}/></>;
}
