#!/usr/bin/env bash
# Mint a short-lived Entire service-account session from a CI job's OIDC token, then run one command with it.
#
#   mint-entire-session.sh [--provider buildkite|depot] --check [-- <command> [args...]]
#   mint-entire-session.sh [--provider buildkite|depot] -- <command> [args...]
#
# The job's OIDC token is exchanged (RFC 8693) at Entire's token endpoint for an "entire:sa-session" token for
# ENTIRE_SERVICE_ACCOUNT_ID. The session reaches only the command after "--", as ENTIRE_TOKEN in its environment.
# No token is printed, written to disk or passed on a command line: curl reads every credential from stdin.
#
# Environment:
#   ENTIRE_SERVICE_ACCOUNT_ID  required, the service account to act as (svc_...)
#   ENTIRE_OIDC_AUDIENCE       audience requested on the CI token (default https://us.auth.entire.io)
#   ENTIRE_TOKEN_URL           Entire token endpoint (default https://us.auth.entire.io/oauth/token)
#   ENTIRE_OIDC_CLIENT_ID      OAuth client presented on the exchange (default entire-cli, Entire's public client)
#   ENTIRE_API_URL             control plane that --check calls (default https://us.console.entire.io)
#   ENTIRE_OIDC_LIFETIME       CI token lifetime in seconds, Buildkite only (default 300)
#   ENTIRE_OIDC_ALLOW_LOOPBACK_HTTP  tests only: set to 1 to allow http://127.0.0.1 endpoints
set -euo pipefail
{ set +x; } 2>/dev/null

provider="" check=0
while [ $# -gt 0 ]; do
  case "$1" in
    --provider)
      [ $# -ge 2 ] || { echo "mint-entire-session: --provider needs buildkite or depot" >&2; exit 64; }
      provider="$2"; shift 2 ;;
    --check) check=1; shift ;;
    --) shift; break ;;
    *) echo "mint-entire-session: unknown argument: $1" >&2; exit 64 ;;
  esac
done
if [ "$check" -eq 0 ] && [ $# -eq 0 ]; then
  echo "mint-entire-session: pass --check or a command after --" >&2
  exit 64
fi
if [ -z "$provider" ]; then
  if [ -n "${BUILDKITE_JOB_ID:-}" ]; then provider=buildkite
  elif [ -n "${ACTIONS_ID_TOKEN_REQUEST_URL:-}" ]; then provider=depot
  else echo "mint-entire-session: not in a Buildkite or Depot CI job; pass --provider" >&2; exit 64
  fi
fi

account="${ENTIRE_SERVICE_ACCOUNT_ID:-}"
audience="${ENTIRE_OIDC_AUDIENCE:-https://us.auth.entire.io}"
token_url="${ENTIRE_TOKEN_URL:-https://us.auth.entire.io/oauth/token}"
client_id="${ENTIRE_OIDC_CLIENT_ID:-entire-cli}"
api_url="${ENTIRE_API_URL:-https://us.console.entire.io}"
lifetime="${ENTIRE_OIDC_LIFETIME:-300}"

if ! [[ "$account" =~ ^svc_[0-9A-HJKMNP-TV-Z]{26}$ ]]; then
  echo "mint-entire-session: ENTIRE_SERVICE_ACCOUNT_ID must be a service account id (svc_ followed by 26 characters)" >&2
  exit 64
fi
if ! [[ "$client_id" =~ ^[A-Za-z0-9._-]{1,128}$ ]] || ! [[ "$lifetime" =~ ^[0-9]{1,5}$ ]] || ! [[ "$audience" =~ ^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~/-]*)?$ ]]; then
  echo "mint-entire-session: ENTIRE_OIDC_CLIENT_ID, ENTIRE_OIDC_LIFETIME or ENTIRE_OIDC_AUDIENCE is malformed" >&2
  exit 64
fi
plain_url() {
  [[ "$1" =~ ^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~/-]*)?$ ]] && return 0
  [ "${ENTIRE_OIDC_ALLOW_LOOPBACK_HTTP:-}" = 1 ] && [[ "$1" =~ ^http://127\.0\.0\.1:[0-9]{1,5}(/[A-Za-z0-9._~/-]*)?$ ]]
}
for url in "$token_url" "$api_url"; do
  plain_url "$url" || { echo "mint-entire-session: $url is not a plain https URL" >&2; exit 64; }
done

jwt_shaped() { [[ "$1" =~ ^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*$ ]]; }
json_string() { sed -n 's/.*"'"$1"'"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1; }

case "$provider" in
  buildkite)
    ci_token="$(buildkite-agent oidc request-token --audience "$audience" --lifetime "$lifetime")" || {
      echo "mint-entire-session: buildkite-agent refused to issue an OIDC token for audience $audience" >&2
      exit 69
    }
    ;;
  depot)
    if [ -z "${ACTIONS_ID_TOKEN_REQUEST_URL:-}" ] || [ -z "${ACTIONS_ID_TOKEN_REQUEST_TOKEN:-}" ]; then
      echo "mint-entire-session: the job has no OIDC request credentials; add 'id-token: write' to its permissions" >&2
      exit 69
    fi
    request_url="${ACTIONS_ID_TOKEN_REQUEST_URL%%\?*}" request_query=""
    case "$ACTIONS_ID_TOKEN_REQUEST_URL" in *\?*) request_query="${ACTIONS_ID_TOKEN_REQUEST_URL#*\?}" ;; esac
    if ! plain_url "$request_url" || ! [[ "$request_query" =~ ^[A-Za-z0-9._~%=\&+-]*$ ]] || ! [[ "$ACTIONS_ID_TOKEN_REQUEST_TOKEN" =~ ^[A-Za-z0-9._~+/=-]+$ ]]; then
      echo "mint-entire-session: the job's OIDC request credentials are malformed" >&2
      exit 69
    fi
    separator='?'
    case "$ACTIONS_ID_TOKEN_REQUEST_URL" in *\?*) separator='&' ;; esac
    encoded_audience="$(printf '%s' "$audience" | sed 's/%/%25/g; s/:/%3A/g; s#/#%2F#g')"
    response="$(printf 'url = "%s%saudience=%s"\nheader = "Authorization: bearer %s"\n' "$ACTIONS_ID_TOKEN_REQUEST_URL" "$separator" "$encoded_audience" "$ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
      | curl -sS --fail --max-time 30 -K -)" || {
      echo "mint-entire-session: Depot refused to issue an OIDC token for audience $audience" >&2
      exit 69
    }
    ci_token="$(printf '%s' "$response" | json_string value)"
    unset response
    ;;
  *) echo "mint-entire-session: unknown provider '$provider' (buildkite or depot)" >&2; exit 64 ;;
esac
if ! jwt_shaped "$ci_token"; then
  echo "mint-entire-session: the $provider OIDC token is not a JWT" >&2
  exit 69
fi

exchange="$(printf '%s' "$ci_token" | curl -sS --max-time 30 -u "$client_id:" -X POST "$token_url" \
  --data-urlencode "grant_type=urn:ietf:params:oauth:grant-type:token-exchange" \
  --data-urlencode "subject_token_type=urn:ietf:params:oauth:token-type:jwt" \
  --data-urlencode "requested_token_type=urn:ietf:params:oauth:token-type:access_token" \
  --data-urlencode "scope=entire:sa-session" \
  --data-urlencode "audience=$account" \
  --data-urlencode "subject_token@-" \
  -w '\n%{http_code}')" || { echo "mint-entire-session: the Entire token endpoint did not answer" >&2; exit 69; }
unset ci_token
status="${exchange##*$'\n'}"
body="${exchange%$'\n'*}"
unset exchange
session="$(printf '%s' "$body" | json_string access_token)"
if [ "$status" != 200 ] || ! jwt_shaped "$session"; then
  code="$(printf '%s' "$body" | json_string error | tr -cd 'a-z_')"
  echo "mint-entire-session: Entire refused the exchange (HTTP $status${code:+, $code}); check the service account's OIDC binding" >&2
  exit 77
fi
unset body
if [ "$provider" = buildkite ] && buildkite-agent redactor add --help >/dev/null 2>&1; then
  printf '%s' "$session" | buildkite-agent redactor add >/dev/null 2>&1 || true
fi

if [ "$check" -eq 1 ]; then
  checked="$(printf 'url = "%s/api/v1/clusters"\nheader = "Authorization: Bearer %s"\n' "${api_url%/}" "$session" \
    | curl -sS --max-time 30 -o /dev/null -w '%{http_code}' -K -)" || checked=000
  if [ "$checked" != 200 ]; then
    echo "mint-entire-session: $api_url refused the minted session (HTTP $checked)" >&2
    exit 77
  fi
  echo "mint-entire-session: minted an Entire session for $account through $provider OIDC, and $api_url accepted it"
  [ $# -eq 0 ] && exit 0
fi

ENTIRE_TOKEN="$session" exec "$@"
