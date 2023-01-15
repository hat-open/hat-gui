import type * as u from '@hat-open/util';


export type LoginFn = (name: string, password: string) => Promise<void>;
export type LogoutFn = () => Promise<void>;
export type SendFn = (adapter: string, name: string, data: u.JData) => Promise<u.JData>;

export type InitFn = () => Promise<void>;
export type VtFn = () => u.VNode;
export type DestroyFn = () => Promise<void>;
export type NotifyFn = (adapter: string, name: string, data: u.JData) => void;

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
    vt: VtFn;
    destroy: DestroyFn | undefined;
    onNotify: NotifyFn | undefined;
};
