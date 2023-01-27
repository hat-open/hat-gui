GUI Server
==========

GUI Server provides user interface for monitoring and controlling
Hat system functionality in real time. It provides multi-user environment
with authentication and authorization control of available resources.


Running
-------

By installing GUI Server from `hat-gui` package, executable `hat-gui`
becomes available and can be used for starting this component.

    .. program-output:: python -m hat.gui --help


Overview
--------

GUI functionality can be defined according to following components:

.. uml::

    folder "Event Server" as EventServer

    folder "GUI Frontend" {
        component Client
        component View
    }

    folder "GUI Backend" {
        component "Eventer Client" as EventerClient

        component Server

        component Adapter <<Adapter>> as Adapter
        component "Adapter Session" <<AdapterSession>> as AdapterSession

        component "View Manager" as ViewManager
    }

    folder "File system" {
        component "View Dir" as ViewDir
    }

    EventServer <--> EventerClient

    EventerClient <-> Adapter

    Adapter ..> AdapterSession : create

    Server <--> AdapterSession

    Server --> ViewManager

    ViewManager ..> ViewDir : get

    Server <--> Client

    Server ..> View : send

Functionality is dependent on active connection to Event Server. Adapters,
Server and View Manager are created when connection with Event Server is
established and destroyed if this connection is closed. If connection with
Event Server is closed, GUI will repeatedly try to establish new connection
with currently active Event Server. If connection to Monitor Server could not
be established or is closed, GUI terminates its process execution.


Adapters
--------

Adapters are mutually independent providers of server-side functionality and
data exposed to GUI frontends. For providing this functionality and data,
adapters rely primarily on their internal state and communication with Event
Server. Adapter definitions are dynamically loaded during GUI server startup
procedure.

GUI server can be configured to initialize arbitrary number of adapter
instances with their custom configurations which will be validated with
associated adapter's optional JSON schema. During adapter instance
initialization, each adapter instance is provided with instance of
EventerClient, enabling queries and event registration. Each adapter is
notified with events sent by Event Server based on it's subscriptions.

Adapter is responsible for creating new instances of AdapterSessions
associated with backend-frontend communication session. AdapterSession
represents adapter's interface to single authenticated frontend client.
It enables full juggler communication - request/response, server state and
server notifications.

Implementation of single adapter is usually split between Adapter
implementation and AdapterSession implementation where Adapter encapsulates
shared data and AdapterSession encapsulates custom data and functionality
specific for each client. Additionally, each AdapterSession is
responsible for enforcing fine grained authorization rules in accordance to
user authenticated with associated AdapterSession.

Adapters available as part of `hat-gui` package:

    .. toctree::
       :maxdepth: 1

       adapters/latest


Views
-----

Views are collection of JavaScript code and other frontend resources
responsible for graphical representation of adapters state and interaction
with user. Each view is represented with content of file system directory.

`ViewManager` is server side component which is used for loading view's
resources. Each file inside view's directory (or subdirectory) is identified
with unix file path relative to view's directory. Each file is read from
file system and encoded as string based on file extension:

    * `.js`, `.css`, `.txt`

        files are read and encoded as `utf-8` encoded strings

    * `.json`, `.yaml`, `.yml`, `.toml`

        files are read as json, yaml or toml files and encoded as `utf-8` json
        data representation

    * `.svg`, `.xml`

        files are read as xml data and encoded as `utf-8` json data
        representing equivalent virtual tree

        .. todo::

            better definition of transformation between xml and virtual
            tree data

    * all other files

        files are read as binary data and encoded as `base64` strings

Server chooses client's view depending on authenticated user configuration.
This view's resources and configuration is obtained from `ViewManager`.
Responsibility of `ViewManager` is to provide current view's data and
configuration as available on file system in the moment when server issued
request for these resources. If view directory contains
`schema.{yaml|yml|json}`, it is used as JSON schema for validating
view's configuration.

Views available as part of `hat-gui` package:

    .. toctree::
       :maxdepth: 1

       views/login

.. todo::

    future improvements:

        * zip archives as view bundles
        * 'smart' ViewManager with watching view directory and conf for changes
          and preloading resources on change


Backend - frontend communication
--------------------------------

Request/response
''''''''''''''''

Juggler request/response communication is used executing system and adapter
specific actions:

    * system actions

        Currently supported system actions are ``login`` and ``logout``,
        defined by ``hat-gui://juggler.yaml#/definitions/request``. All
        requests return ``null`` on success and raise exception in case of
        error.

    * adapter specific actions

        Request name is formatted as ``<adapter>/<action>`` where ``<adapter>``
        is name of adapter instance and ``<action>`` is one of action
        names supported by referenced adapter instance type. Structure
        of request data and response results are defined by specific
        adapter action.

Because AdapterSessions are created only for authenticated users, adapter
specific actions are available only after successful authentication.


Server state
''''''''''''

Juggler state is used for transfer of AdapterSession states from backend to
frontend. State is single object where keys represent adapter instance names
and values contain current associated AdapterSession state. If client
is not authenticated, this object is empty.


Server notifications
''''''''''''''''''''

Juggler notifications enable backend to notify frontend with system and
adapter specific notifications:

    * system notifications

        Currently supported system notification is ``init`` defined by
        ``hat-gui://juggler.yaml#/definitions/notification``. Backend can
        send this notification at any time, informing frontend of changes
        that should be applied to frontend execution environment.

    * adapter specific notifications

        Notification name is formatted as ``<adapter>/<notification>`` where
        ``<adapter>`` is name of adapter instance and ``<notification>`` is
        notification identification supported by referenced adapter instance
        type. Structure of notification data is defined by specific
        adapter notification.


Frontend API
------------

Initially, each instance of client is considered unauthenticated and not
initialized. Once client receives server's ``init`` notification, it should
create new execution environment and initialize view defined as part of
``init`` data.

View initialization is based on evaluation of JavaScript code from
view's `index.js`. This code is evaluated inside environment which contains
global constant ``hat`` which is also bound to ``window`` object. When
evaluation is finished, environment should contain global values ``init``,
``vt``, ``destroy``, ``onNotify`` and ``onDisconnected``.

If juggler connection to server is broken, last initialized view remains
active until new connection is established and new ``init`` notification
is received. Each time new juggler connection is established, server will
send new ``init`` notification.

Client bounds juggler connection's server state to default renderer's
``['remote']`` path. Constant ``hat``, available during execution of
`index.js`, references object with properties:

    * ``conf``

        view's configuration

    * ``user``

        authenticated user identifier

    * ``roles``

        authenticated user roles

    * ``view``

        view's data

    * `login(name, password)`

        login method

    * `logout()`

        logout method

    * `send(adapter, name, data)`

        method for request/response communication

    * `getServerAddresses()`

        get GUI server juggler addresses

    * `setServerAddresses(addresses)`

        set GUI server juggler addresses

    * `disconnect()`

        close current juggler connection to GUI server

When evaluation finishes, environment should contain optional functions:

    * ``init()``

        called immediately after evaluation of `index.js` finishes

    *  ``vt()``

        called each time global renderer's state changes (this function should
        return virtual tree data)

    * ``destroy()``

        called prior to evaluation of other view's `index.js`

    * ``onNotify(adapter, name, data)``

        called each time client receives adapter specific notification from
        server

    * ``onDisconnected()``

        called if juggler connection is broken

.. todo::

    describe `exports` and resulting environment in case of js modules


JSON Schemas
------------

Configuration
'''''''''''''

.. literalinclude:: ../schemas_json/main.yaml
    :language: yaml


Juggler
'''''''

.. literalinclude:: ../schemas_json/juggler.yaml
    :language: yaml


TypeScript definitions
----------------------

.. literalinclude:: ../src_js/api.d.ts
    :language: ts
