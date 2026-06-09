#!/bin/bash
set -e

# Ascend env scripts exist only inside the runtime image; use source=/dev/null
# so ShellCheck does not require those paths at lint time.
load_env_script() {
    local script="$1"
    if [ -f "$script" ]; then
        # shellcheck source=/dev/null
        . "$script"
    fi
}

cat /workspace/agreement.txt

load_env_script /usr/local/Ascend/ascend-toolkit/set_env.sh

shopt -s nullglob
for set_env in /usr/local/Ascend/cann-*/share/info/ascendnpu-ir/bin/set_env.sh; do
    load_env_script "$set_env"
    break
done

load_env_script /usr/local/Ascend/nnal/atb/set_env.sh

exec "$@"
