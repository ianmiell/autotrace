#!/bin/bash
sudo python autotrace/autotrace.py -l . 'nmap localhost' 'strace -p PID' 'tcpdump -XXs 20000'
