#!/bin/bash
sudo autotrace 'nmap localhost' 'strace -p PID' 'tcpdump -XXs 20000'
