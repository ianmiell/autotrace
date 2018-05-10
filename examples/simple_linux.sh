#!/bin/bash
sudo autotrace 'find /' 'strace -p PID' 'vmstat 1'
