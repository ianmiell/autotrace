#!/bin/bash
sudo telemetrise 'nmap localhost' 'strace -p PID' 'tcpdump -XXs 20000'
