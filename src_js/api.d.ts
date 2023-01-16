import type { Renderer } from '@hat-open/renderer';
import type * as u from '@hat-open/util';


export type LoginFn = (name: string, password: string) => Promise<void>;
export type LogoutFn = () => Promise<void>;
export type SendFn = (adapter: string, name: string, data: u.JData) => Promise<u.JData>;

export type InitFn = () => Promise<void>;
export type VtFn = () => u.VNode;
export type DestroyFn = () => Promise<void>;
export type NotifyFn = (adapter: string, name: string, data: u.JData) => Promise<void>;
export type DisconnectedFn = () => Promise<void>;

export type Hat = {
    conf: u.JData;
    user: string | null;
    roles: string[];
    view: Record<string, u.JData>;
    login: LoginFn;
    logout: LogoutFn;
    send: SendFn;
};

export type Env = {
    hat: Hat;
    init: InitFn | undefined;
    vt: VtFn | undefined;
    destroy: DestroyFn | undefined;
    onNotify: NotifyFn | undefined;
    onDisconnected: DisconnectedFn | undefined;
};

export type Util = typeof u;

declare global {
    var hat: Hat;
    var r: Renderer;
    // TODO export util types
    var u: Util;
}
