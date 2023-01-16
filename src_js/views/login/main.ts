// TODO import type shadows global u
import * as u from '@hat-open/util';

import '../../api';

import '../../../src_scss/views/login/main.scss';


type State = {
    name: string;
    password: string;
    message: string | null;
    loading: boolean;
    disconnected: boolean;
};

const defaultState: State = {
    name: '',
    password: '',
    message: null,
    loading: false,
    disconnected: false
};


export async function init() {
    await r.set('view', defaultState);
}


export async function onDisconnected() {
    await r.set(['view', 'disconnected'], true);
}


export function vt() {
    const state = r.get('view') as (State | null);
    if (!state)
        return ['div.login'];

    if (state.loading)
        return ['div.loading',
            'Loading'
        ];

    if (state.disconnected)
        return ['div.disconnected',
            'Disconnected'
        ];

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
        inputVt('text', 'Name', state.name, r.set(['view', 'name']) as any),
        inputVt('password', 'Password', state.password, r.set(['view', 'password']) as any),
        ['button', {
            on: {
                click: login
            }},
            'Login'
        ]
    ];
}


function inputVt(
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
                change: (evt: Event) => changeCb((evt.target as HTMLInputElement).value)
            }
        }]
    ];
}


async function login() {
    const state = r.get('view') as State;
    try {
        await hat.login(state.name, state.password);
        r.set(['view', 'loading'], true);

    } catch(e) {
        r.set(['view', 'message'], String(e));
    }
}
