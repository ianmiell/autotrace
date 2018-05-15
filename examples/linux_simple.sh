#!/bin/bash
sudo python autotrace/autotrace.py -l . 'find /' 'strace -p PID' 'vmstat 1'
