#!/bin/bash
sudo python autotrace/autotrace.py 'find /' 'strace -p PID' 'vmstat 1'
