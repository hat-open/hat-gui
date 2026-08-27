GUI Server
==========

GUI Server provides user interface for monitoring and controlling
Hat system functionality in real time. It provides multi-user environment
with authentication and authorization control of available resources.


Running
-------

By installing GUI Server from `hat-gui` package, executable `hat-gui-server`
becomes available and can be used for starting this component.

.. program-output:: python -m hat.gui.server --help


Overview
--------

GUI functionality can be defined according to following components:

.. uml::

    folder "Event Server" as EventServer

    folder "GUI Frontend" {
        component View
    }

    folder "GUI Backend" {
        component "Eventer Client" as EventerClient

        component Server

        component Adapter <<Adapter>> as Adapter
        component "Adapter Session" <<AdapterSession>> as AdapterSession

        component "User Session" <<UserSession>> as UserSession
    }

    folder "File system" {
        component "View Dir" as ViewDir
    }

    EventServer <--> EventerClient

    EventerClient <-> Adapter

    Adapter ..> AdapterSession : create

    Server <--> AdapterSession

    Server ..> UserSession : create

    Server ..> ViewDir : get

    Server <--> View


Functionality is dependent on active connection to Event Server. Adapters and
Server are created when connection with Event Server is established and
destroyed if this connection is closed. If connection with Event Server is
closed, GUI will repeatedly try to establish new connection with currently
active Event Server. If connection to Monitor Server could not be established
or is closed, GUI terminates its process execution.

GUI Server can also run independently of Monitor Server. In this case,
GUI Server connects to predefined Event Server address. If this connection
could not be established or is broken, GUI Server terminates it's process
execution.

When connecting to Event Server, GUI will use client name
``gui/<name>`` where `<name>` represents configured component's name.


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
notified with events sent by Event Server based on its subscriptions.

Server is responsible for creating new instances of AdapterSessions
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

Views are collection of frontend resources (HTML, JavaScript, CSS, ...)
responsible for graphical representation of adapters state and interaction
with user. Each view is represented with content of file system directory.
These files can be obtained by frontend using HTTP GET requests.

Server chooses client's view depending on authenticated user and its associated
roles. Ordered list of all available views is defined as part of GUI Server's
configuration where each view has its associated roles. Server chooses first
view that has at least one role matching one of authenticated user roles.

In addition to views for authenticated users, GUI Server's configuration
defines single view that is available to non authenticated users.

Views available as part of `hat-gui` package:

.. toctree::
   :maxdepth: 1

   views/login


User sessions
-------------

User session is server side resource that represents lifetime of authenticated
user session. It is uniquely identified with ``SESSION_ID`` that is provided
as HTTP cookie as part of all HTTP requests sent from frontend to backend.

New user session is created after successful authentication procedure. Lifetime
of user session is determined by server based on:

* ...

Once user session is closed, future HTTP requests identifying this session
are considered unauthenticated. All active websocket connections, that are
associated with session being closed, are closed during closing of session.


Backend - frontend communication
--------------------------------

REST Communication
''''''''''''''''''

endpoints

* '/login'
* '/logout'
* '/user'


Juggler Communication
'''''''''''''''''''''

available only to authenticated users

'/ws' endpoint

* request/response

  Juggler request/response communication is used for executing adapter
  specific actions. Request name is formatted as ``<adapter>/<action>`` where
  ``<adapter>`` is name of adapter instance and ``<action>`` is one of action
  names supported by referenced adapter instance type. Structure of request
  data and response results are defined by specific adapter action.

* server state

  Juggler state is used for transfer of AdapterSession states from backend to
  frontend. State is single object where keys represent adapter instance names
  and values contain current associated AdapterSession state.

* server notifications

  Juggler notifications enable backend to notify frontend with adapter specific
  notifications. Notification name is formatted as ``<adapter>/<notification>``
  where ``<adapter>`` is name of adapter instance and ``<notification>`` is
  notification identification supported by referenced adapter instance
  type. Structure of notification data is defined by specific
  adapter notification.


GUI events
----------

In addition to events registered by Adapters, Server registers events
representing current state of authenticated Clients. These events have
event type::

    gui/<name>/clients

where ``<name>`` represents configured Server's name.

Payload for clients events is defined by
``hat-gui://events.yaml#/$defs/events/clients``.


JSON Schemas
------------

Configuration
'''''''''''''

.. literalinclude:: ../schemas_json/server.yaml
    :language: yaml


Events
''''''

.. literalinclude:: ../schemas_json/events.yaml
    :language: yaml


OpenAPI Schema
--------------

.. literalinclude:: ../schemas_openapi/server.yaml
    :language: yaml
