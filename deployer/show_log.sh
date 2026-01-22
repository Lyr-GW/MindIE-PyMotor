#!/usr/bin/env bash

cd ./log_collect

setsid nohup python3 -u log_monitor.py > output.log 2>&1 </dev/null &

timeout 2 tail -f output.log
