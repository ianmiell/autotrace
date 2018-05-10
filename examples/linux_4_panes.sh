#!/bin/bash
sudo autotrace 'nmap localhost' 'strace -p PID' 'tcpdump -XXs 20000' 'bash -c "while true; do free; sleep 5; done"'
