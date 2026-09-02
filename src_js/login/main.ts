import r from '@hat-open/renderer';
import * as u from '@hat-open/util';


type State = {
    name: string;
    password: string;
    message: string | null;
};

const defaultState: State = {
    name: '',
    password: '',
    message: null
};

type Conf = {
    showLoginForm: boolean;
    oidcProviders: string[];
};

let conf: Conf | null = null;


async function main() {
    const confResponse = await fetch('conf.json');
    conf = await confResponse.json();

    const root = document.body.appendChild(document.createElement('div'));
    r.init(root, defaultState, vt);
}


function vt(): u.VNode {
    const state = r.get() as State;
    const showLoginForm = conf?.showLoginForm ?? true;
    const oidcProviders = conf?.oidcProviders ?? [];

    return ['div.container',
        showLoginForm ?
            ['div.login', {
                on: {
                    keyup: (evt: KeyboardEvent) => {
                        if (evt.key == 'Enter')
                            login();
                    }
                }},
                (state.message == null ? [] : ['div.message',
                    state.message
                ]),
                inputStringVt(
                    'text', 'Name', state.name,
                    value => r.set(['name'], value)
                ),
                inputStringVt(
                    'password', 'Password', state.password,
                    value => r.set(['password'], value)
                ),
                ['button', {
                    on: {
                        click: login
                    }},
                    'Login'
                ]
            ] : [],
        oidcProviders.length > 0 ?
            ['div.oidc-providers',
                oidcProviders.map(oidcProviderButtonVt)
            ] : []
    ];
}


function inputStringVt(
    type: string, label: string, value: string, changeCb: (value: string) => void
): u.VNodeChild {
    return [
        ['label', label],
        ['input', {
            props: {
                type: type,
                value: value
            },
            on: {
                change: (evt: Event) => {
                    changeCb((evt.target as HTMLInputElement).value);
                }
            }
        }]
    ];
}


function oidcProviderButtonVt(name: string): u.VNode {
    return ['button', {
        on: {
            click: () => {
                window.location.assign(
                    `/login/oidc/${encodeURIComponent(name)}`);
            }
        }},
        `Sign in with ${name}`
    ];
}


async function login() {
    const state = r.get() as State;
    try {
        const res = await fetch('/login/local', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                name: state.name,
                password: state.password
            })
        });

        if (res.status != 200)
            throw new Error(await res.text());

        window.location.assign('/');

    } catch(e) {
        r.change(u.pipe(
            u.set('message', String(e)),
            u.set('password', '')
        ));
    }
}

window.addEventListener('load', main);
