#!/bin/bash
sudo telemetrise 'find /' 'strace -p PID' 'vmstat 1'
