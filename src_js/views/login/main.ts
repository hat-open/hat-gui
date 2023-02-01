// TODO import type shadows global u
import * as u from '@hat-open/util';

import type * as _ from '../../api';  // eslint-disable-line @typescript-eslint/no-unused-vars

import '../../../src_scss/views/login/main.scss';


type State = {
    name: string;
    password: string;
    remember: boolean;
    message: string | null;
    loading: boolean;
    disconnected: boolean;
};

type LocalStorageData = {
    name: string;
    password: string;
};

const defaultState: State = {
    name: '',
    password: '',
    remember: true,
    message: null,
    loading: false,
    disconnected: false
};

const localStorageKey = 'hat_builtin_login';


export async function init() {
    const localStorageData = loadLocalStorageData();
    const state = (!localStorageData ?
        defaultState :
        u.pipe(
            u.set('name', localStorageData.name),
            u.set('password', localStorageData.password)
        )(defaultState)
    );

    hat.setLogoutAction(async () => {
        saveLocalStorageData(null);
    });

    await r.set('view', state);

    if (localStorageData)
        await login();
}


export async function onDisconnected() {
    await r.set(['view', 'disconnected'], true);
}


export function vt() {
    const state = r.get('view') as (State | null);
    if (!state)
        return ['div.login'];

    if (state.disconnected)
        return ['div.disconnected',
            ['div', 'Disconnected'],
            ['div', 'Trying to reconnect...']
        ];

    if (state.loading)
        return ['div.loading',
            ['div', 'Loading...']
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
        await hat.login(state.name, state.password);

        r.set(['view', 'loading'], true);
        saveLocalStorageData(state.remember ?
            {name: state.name, password: state.password} :
            null
        );

    } catch(e) {
        r.change('view', u.pipe(
            u.set('message', String(e)),
            u.set('password', '')
        ));
        saveLocalStorageData(null);
    }
}


function saveLocalStorageData(data: LocalStorageData | null) {
    if (!data) {
        window.localStorage.removeItem(localStorageKey);
        return;
    }

    window.localStorage.setItem(localStorageKey, hexEncode(data));
}


function loadLocalStorageData(): LocalStorageData | null {
    const dataStr = window.localStorage.getItem(localStorageKey);
    if (!dataStr)
        return null;

    const data = hexDecode(dataStr);
    if (!isLocalStorageData(data))
        return null;

    return data;
}


function hexEncode(data: u.JData): string {
    const dataStr = JSON.stringify(data);
    let dataHex = '';
    for (let i = 0; i < dataStr.length; ++i)
        dataHex += dataStr.charCodeAt(i).toString(16).padStart(4, '0');
    return dataHex;
}


function hexDecode(data: string): u.JData {
    let dataStr = '';
    for (let i = 0; i < data.length; i += 4)
        dataStr += String.fromCharCode(parseInt(data.slice(i, i + 4), 16));
    return JSON.parse(dataStr);
}


function isLocalStorageData(data: unknown): data is LocalStorageData {
    return u.isObject(data) && u.isString(data.name) && u.isString(data.password);
}
