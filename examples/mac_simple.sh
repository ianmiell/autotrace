#!/bin/bash
sudo python autotrace/autotrace.py -l . 'find /' 'dtruss -f -p PID' 'iostat 1'
