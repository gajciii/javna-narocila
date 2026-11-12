import { useEffect, useState } from 'react';
import App from './App';
import HomePage from './HomePage';

/** The public home page is independent of the existing application and API. */
export default function Root() {
    const [route, setRoute] = useState(() => window.location.hash.slice(1) || '/');
    useEffect(() => {
        const update = () => {
            setRoute(window.location.hash.slice(1) || '/');
            window.scrollTo(0, 0);
        };
        window.addEventListener('hashchange', update);
        return () => window.removeEventListener('hashchange', update);
    }, []);
    return route === '/' || route === '/domov' ? <HomePage /> : <App />;
}
