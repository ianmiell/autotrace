#!/bin/bash
sudo telemetrise 'find /' 'dtruss -f -p PID' 'iostat 1'
