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

Mac example:

```
$ telemetrise -c 'find /' -l 'dtruss -f -p PID' -r 'iostat 1'
```

PID is replaced with the PID of the main (-c) command


Linux example with strace and vmstat:

```
$ telemetrise -c 'find /' -l 'strace -p PID' -r 'vmstat 1'
```
