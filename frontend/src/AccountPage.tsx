import EmailNotificationSettings from './EmailNotificationSettings';

export default function AccountPage(_props: { user: { username: string }; signOut: () => Promise<void> }) {
    return <>
        <section className="page-intro simple-intro building-intro" aria-labelledby="account-page-title"><div className="page-heading"><div><h1 id="account-page-title">Moj račun</h1><p>Nastavitve, ki veljajo samo za vas, ne glede na izbrano podjetje.</p></div></div></section>
        <div className="account-page">
            <EmailNotificationSettings/>
        </div>
    </>;
}
