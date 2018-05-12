#!/bin/bash
sudo python autotrace/autotrace.py 'find /' 'dtruss -f -p PID' 'iostat 1'
