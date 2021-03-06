import r from '@hat-open/renderer';
import * as u from '@hat-open/util';
import * as juggler from '@hat-open/juggler';


let viewManager = null;


const defaultState = {
    local: {},
    remote: null
};


function main() {
    viewManager = new ViewManager();
    const root = document.body.appendChild(document.createElement('div'));
    r.init(root, defaultState, () => viewManager.vt());
    viewManager.app = new juggler.Application('local', 'remote');
    window.viewManager = viewManager;
}


class ViewManager {

    constructor() {
        this._app = null;
        this._view = null;
        this._hat = null;
    }

    get app() {
        return this._app;
    }

    get view() {
        return this._view;
    }

    get hat() {
        return this._hat;
    }

    set app(app) {
        this._app = app;
        if (app) {
            app.addEventListener('message', evt => this._onMessage(evt.detail));
        }
    }

    vt() {
        if (!this.view)
            return ['div'];
        return this.view.vt();
    }

    _onMessage(msg) {
        if (msg.type == 'state') {
            this._initView(msg);
        } else if (msg.type == 'adapter') {
            if (this.hat) {
                this.hat.conn.addMessage(msg.name, msg.data);
            }
        } else {
            throw new Error(`received invalid message type: ${msg.type}`);
        }
    }

    async _initView(msg) {
        if (this.view) {
            if (this.view.destroy)
                await this.view.destroy();
            this._view = null;
            this._hat = null;
        }
        await r.set(defaultState);
        r.render();
        document.head.querySelectorAll('style').forEach(
            node => node.parentNode.removeChild(node));
        this._hat = {
            conf: msg.conf,
            reason: msg.reason,
            user: msg.user,
            roles: msg.roles,
            view: msg.view,
            conn: new ViewConnection(this.app)
        };
        const src = u.get('index.js', msg.view);
        if (!src)
            return;
        const fn = new Function(
            'hat', `var exports = {};\n${src}\nreturn exports;`);
        const view = fn(this.hat);
        if (view.init)
            await view.init();
        this._view = view;
    }
}


class ViewConnection {

    constructor(conn) {
        this._conn = conn;
        this._onMessage = null;
    }

    addMessage(adapter, msg) {
        if (this._onMessage) {
            this._onMessage(adapter, msg);
        }
    }

    /**
     * Set on adapter message callback
     * @type {function(string, *)}
     */
    set onMessage(cb) {
        this._onMessage = cb;
    }

    /**
     * Login
     * @param {string} name
     * @param {string} password
     */
    login(name, password) {
        this._conn.send({
            type: 'login',
            name: name,
            password: password
        });
    }

    /**
     * Logout
     */
    logout() {
        this._conn.send({ type: 'logout' });
    }

    /**
     * Send adapter message
     * @param {string} adapter adapter name
     * @param {*} msg message
     */
    send(adapter, msg) {
        this._conn.send({
            type: 'adapter',
            name: adapter,
            data: msg
        });
    }
}


window.addEventListener('load', main);
window.r = r;
window.u = u;
