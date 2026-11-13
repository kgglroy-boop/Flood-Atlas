#!/bin/sh
# Validate before delegating to the image's real initialization entrypoint.
set -eu

if [ "$#" -lt 2 ]; then
    printf '%s\n' 'Password guard requires a credential name and an entrypoint.' >&2
    exit 64
fi

credential_name=$1
shift
case "$credential_name" in
    POSTGRES_PASSWORD) credential_value=${POSTGRES_PASSWORD:-} ;;
    GEOSERVER_ADMIN_PASSWORD) credential_value=${GEOSERVER_ADMIN_PASSWORD:-} ;;
    *) printf '%s\n' 'Unsupported credential name.' >&2; exit 64 ;;
esac

case "$credential_value" in
    ''|CHANGE_ME)
        printf '%s is not configured; refusing service initialization.\n' "$credential_name" >&2
        exit 78
        ;;
esac
case "$credential_value" in
    *[![:space:]]*) ;;
    *) printf '%s is blank; refusing service initialization.\n' "$credential_name" >&2; exit 78 ;;
esac

exec "$@"
