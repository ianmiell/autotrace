#!/bin/bash
sudo python autotrace/autotrace.py 'nmap localhost' 'strace -p PID' 'tcpdump -XXs 20000' 'bash -c "while true; do free; sleep 5; done"'
