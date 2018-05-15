#!/bin/bash
sudo python autotrace/autotrace.py -l . 'nmap localhost' 'strace -p PID' 'tcpdump -XXs 20000' 'bash -c "while true; do free; sleep 5; done"' 'bash -c "while true; do lsof -p PID | tail -5; sleep 5; done"'
