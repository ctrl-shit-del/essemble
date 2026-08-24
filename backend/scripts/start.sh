#!/usr/bin/env sh
# Production entrypoint.
#
# Bind 0.0.0.0, never 127.0.0.1: a container-hosted service that binds
# loopback is unreachable from outside the container and the platform's
# health check fails with no error in the application log.
#
# The port comes from $PORT, which the host assigns. 10000 is the documented
# default and is only a fallback -- hardcoding a port makes the service
# unroutable the moment the host picks a different one.
set -eu
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}"
