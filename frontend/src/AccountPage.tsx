import { LogOut, UserRound } from 'lucide-react';
import EmailNotificationSettings from './EmailNotificationSettings';

export default function AccountPage({ user, signOut }: { user: { username: string }; signOut: () => Promise<void> }) {
    return <>
        <section className="page-intro simple-intro building-intro" aria-labelledby="account-page-title"><div className="page-heading"><div><h1 id="account-page-title">Moj račun</h1><p>Nastavitve, ki veljajo samo za vas, ne glede na izbrano podjetje.</p></div></div></section>
        <div className="account-page">
            <section className="surface account-summary" aria-label="Prijava">
                <UserRound size={20}/><div><strong>{user.username}</strong><span>Prijavljeni ste s tem naslovom.</span></div>
                <button className="button small" onClick={() => void signOut()}><LogOut size={15}/>Odjava</button>
            </section>
            <EmailNotificationSettings/>
        </div>
    </>;
}
