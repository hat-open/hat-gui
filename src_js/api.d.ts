import type { Renderer } from '@hat-open/renderer';
import type * as u from '@hat-open/util';


export type LogoutAction = (user: string | null) => Promise<void>;

export type LoginFn = (name: string, password: string) => Promise<void>;
export type LogoutFn = () => Promise<void>;
export type SendFn = (adapter: string, name: string, data: u.JData) => Promise<u.JData>;
export type GetServerAddressesFn = () => string[];
export type SetServerAddressesFn = (addresses: string[]) => void;
export type DisconnectFn = () => void;
export type SetLogoutActionFn = (action: LogoutAction | null) => void;

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
    getServerAddresses: GetServerAddressesFn;
    setServerAddresses: SetServerAddressesFn;
    disconnect: DisconnectFn;
    setLogoutAction: SetLogoutActionFn;
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
    var hat: Hat;  // eslint-disable-line no-var
    var r: Renderer;  // eslint-disable-line no-var
    // TODO export util types
    var u: Util;  // eslint-disable-line no-var
}
