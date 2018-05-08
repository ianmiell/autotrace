# telemetrise

Runs a process, and gives you the output along with other telemetry on the
process, all in one terminal window.

Here's me seeing what nmap does by looking at strace and tcpdump.

[![asciicast](https://asciinema.org/a/NUXLnqDrc6rD48gd3KcbQT2Dq.png)](https://asciinema.org/a/NUXLnqDrc6rD48gd3KcbQT2Dq)

Features:

- Pause program in-flight to see what's going on

## Install

```
# Requires:
# python (2 or 3)
# pip
pip install telemetrise
```


## Examples

Mac example:

```
$ sudo telemetrise -c 'find /' -l 'dtruss -f -p PID' -r 'iostat 1'
```

PID is replaced with the PID of the main (-c) command


Linux example with strace and vmstat:

```
$ sudo telemetrise -c 'find /' -l 'strace -p PID' -r 'vmstat 1'
`

``
Linux example with strace and tcpdump:

```
$ sudo telemetrise -c 'nmap localhost' -l 'strace -p PID' -r 'tcpdump -XXs 20000'
