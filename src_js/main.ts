import r from '@hat-open/renderer';
import * as u from '@hat-open/util';
import * as juggler from '@hat-open/juggler';

import * as api from './api';


type InitMsg = {
    user: string | null;
    roles: string[];
    view: Record<string, u.JData> | null;
    conf: u.JData;
};


let app: juggler.Application;
let env: api.Env | null = null;


function main() {
    const root = document.body.appendChild(document.createElement('div'));
    r.init(root, null, vt);
    app = new juggler.Application('remote');

    const events: (juggler.Notification | 'disconnected')[] = [];
    const eventLoop = async () => {
        while (events.length) {
            const event = events[0];
            if (event == 'disconnected') {
                await onDisconnected();
            } else {
                await onNotify(event);
            }
            events.shift();
        }
    };

    app.addEventListener('disconnected', () => {
        events.push('disconnected');
        if (events.length > 1)
            return;
        eventLoop();
    });

    const notifications: juggler.Notification[] = [];
    app.addEventListener('notify', (evt: Event) => {
        events.push((evt as juggler.NotifyEvent).detail);
        if (events.length > 1)
            return;
        eventLoop();
    });
}


function vt(): u.VNode {
    if (!env || !env.vt)
        return ['div'];

    return env.vt();
}


async function onNotify(notification: juggler.Notification) {
    if (notification.name == 'init') {
        await initView(notification.data as InitMsg);
        return;
    }

    if (!env || !env.onNotify)
        return;

    const [adapter, name] = notification.name.split('/');
    await env.onNotify(adapter, name, notification.data);
}


async function onDisconnected() {
    if (!env || !env.onDisconnected)
        return;

    await env.onDisconnected();
}


async function initView(msg: InitMsg) {
    if (env) {
        if (env.destroy)
            await env.destroy();
        document.head.querySelectorAll('style').forEach(node =>
            node.parentNode?.removeChild(node)
        );
        env = null;
    }

    await r.change(state => {
        return {remote: u.get('remote', state)};
    });

    if (msg.view == null)
        return;

    const src = u.get('index.js', msg.view);
    if (!u.isString(src))
        return;

    const hat: api.Hat = {
        conf: msg.conf,
        user: msg.user,
        roles: msg.roles,
        view: msg.view,
        login: login,
        logout: logout,
        send: send,
    };
    (window as any).hat = hat;
    if (globalThis)
        globalThis.hat = hat;

    const fn = new Function(
        'hat', `var exports = {hat: hat};\n${src}\nreturn exports;`);
    env = fn(hat);

    if (env && env.init)
        await env.init();
}


async function login(name: string, password: string) {
    await app.send('login', {name, password});
}


async function logout() {
    await app.send('logout', null);
}


async function send(adapter: string, name: string, data: u.JData): Promise<u.JData> {
    return await app.send(`${adapter}/${name}`, data);
}


window.addEventListener('load', main);
[window, globalThis].forEach(i => {
    if (i) {
        (i as any).r = r;
        (i as any).u = u;
        (i as any).hat = null;
    }
});
