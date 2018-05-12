#!/bin/bash
sudo python autotrace/autotrace.py 'nmap localhost' 'strace -p PID' 'tcpdump -XXs 20000'
