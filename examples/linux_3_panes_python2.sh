#!/bin/bash
sudo python2 autotrace/autotrace.py -l . 'nmap localhost' 'strace -p PID' 'tcpdump -XXs 20000'
