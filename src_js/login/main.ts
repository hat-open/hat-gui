import r from '@hat-open/renderer';
import * as u from '@hat-open/util';


type State = {
    name: string;
    password: string;
    remember: boolean;
    message: string | null;
};


const defaultState: State = {
    name: '',
    password: '',
    remember: false,
    message: null
};


async function main() {
    const root = document.body.appendChild(document.createElement('div'));
    r.init(root, defaultState, vt);
}


function vt(): u.VNode {
    const state = r.get() as State;

    return ['div.login', {
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
            value => r.set(['view', 'name'], value)
        ),
        inputStringVt(
            'password', 'Password', state.password,
            value => r.set(['view', 'password'], value)
        ),
        inputBooleanVt(
            'Remember me', state.remember,
            value => r.set(['view', 'remember'], value)
        ),
        ['button', {
            on: {
                click: login
            }},
            'Login'
        ]
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


function inputBooleanVt(
    label: string, value: boolean, changeCb: (value: boolean) => void
): u.VNodeChild {
    return [
        ['label.input',
            ['input', {
                props: {
                    type: 'checkbox',
                    checked: value
                },
                on: {
                    change: (evt: Event) => {
                        changeCb((evt.target as HTMLInputElement).checked);
                    }
                }
            }],
            label
        ]
    ];
}


async function login() {
    const state = r.get('view') as State;
    try {
        const res = await fetch('/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                name: state.name,
                password: state.password,
                remember: state.remember
            })
        });

        if (res.status != 200)
            throw new Error(String(res.body));

        window.location.assign('/index.html');

    } catch(e) {
        r.change(u.pipe(
            u.set('message', String(e)),
            u.set('password', '')
        ));
    }
}


window.addEventListener('load', main);
