#!/bin/bash
set -e

cat /workspace/agreement.txt

if [ -f /usr/local/Ascend/ascend-toolkit/set_env.sh ]; then
    # shellcheck disable=SC1091
    source /usr/local/Ascend/ascend-toolkit/set_env.sh
fi
for set_env in /usr/local/Ascend/cann-*/share/info/ascendnpu-ir/bin/set_env.sh; do
    if [ -f "$set_env" ]; then
        # shellcheck disable=SC1090
        source "$set_env"
        break
    fi
done
if [ -f /usr/local/Ascend/nnal/atb/set_env.sh ]; then
    # shellcheck disable=SC1091
    source /usr/local/Ascend/nnal/atb/set_env.sh
fi

exec "$@"
