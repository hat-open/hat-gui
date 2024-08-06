#!/bin/sh

set -e

PLAYGROUND_PATH=$(dirname "$(realpath "$0")")
. $PLAYGROUND_PATH/env.sh

LOG_LEVEL=DEBUG
CONF_PATH=$DATA_PATH/gui.yaml

PASSWORD="$($PYTHON -m hat.gui.passwd pass1)"

cat >$CONF_PATH <<EOF
log:
    version: 1
    formatters:
        console_formatter:
            format: "[%(asctime)s %(levelname)s %(name)s] %(message)s"
        syslog_formatter: {}
    handlers:
        console_handler:
            class: logging.StreamHandler
            formatter: console_formatter
            level: DEBUG
        syslog_handler:
            class: hat.syslog.handler.SyslogHandler
            host: '127.0.0.1'
            port: 6514
            comm_type: TCP
            level: DEBUG
            formatter: syslog_formatter
    loggers:
        hat.gui:
            level: $LOG_LEVEL
    root:
        level: INFO
        handlers:
            - console_handler
            - syslog_handler
    disable_existing_loggers: false
name: gui
event_server:
    require_operational: true
    eventer_server:
        host: "127.0.0.1"
        port: 23012
address:
    host: "127.0.0.1"
    port: 23023
adapters: []
views:
  - name: login
    builtin: login
    conf: null
users:
  - name: user1
    password: $PASSWORD
    roles: []
    view: null
initial_view: login
EOF

exec $PYTHON -m hat.gui.server --conf $CONF_PATH
