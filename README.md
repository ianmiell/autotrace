# telemetrise

Runs a process, and gives you the output along with other telemetry on the
process, all in one terminal window.

Currently shows:

- strace

- vmstat

but other suggestions are welcome.

Requires/supports:

- python3

- pip install pexpect

- pip install curtsies

## Examples

Linux example with strace and vmstat

```
$ telemetrise --command 'find /' --bottom_left_window 'strace -p PID' --bottom_right_window 'vmstat 1'
```
