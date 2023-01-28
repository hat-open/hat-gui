#!/bin/sh

. $(dirname -- "$0")/env.sh

LOG_LEVEL=DEBUG
CONF_PATH=$DATA_PATH/gui.yaml

PASSWORD="$($PYTHON -m hat.gui.passwd pass1)"

cat > $CONF_PATH << EOF
type: gui
log:
    version: 1
    formatters:
        console_formatter:
            format: "[%(asctime)s %(levelname)s %(name)s] %(message)s"
    handlers:
        console_handler:
            class: logging.StreamHandler
            formatter: console_formatter
            level: DEBUG
    loggers:
        hat.gui:
            level: $LOG_LEVEL
    root:
        level: INFO
        handlers: ['console_handler']
    disable_existing_loggers: false
address: "http://127.0.0.1:23023"
adapters: []
views:
  - name: login
    builtin: login
    conf: null
initial_view: login
users:
  - name: user1
    password: $PASSWORD
    roles: []
    view: null
event_server_address: "tcp+sbs://127.0.0.1:23012"
EOF

exec $PYTHON -m hat.gui --conf $CONF_PATH
