#!/bin/sh

. $(dirname -- "$0")/env.sh

cd $ROOT_PATH

export NODE_OPTIONS=--openssl-legacy-provider
exec $PYTHON -m doit
