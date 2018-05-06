from __future__ import unicode_literals
import pexpect
import curtsies
import time
import sys
from curtsies.fmtfuncs import blue, red, green
from curtsies.formatstring import linesplit

def main(command):
	pexpect_session = pexpect.spawn(command)
	command_pid = pexpect_session.pid
	pexpect.run('kill -STOP $PID')
	# Assumes strace exists... need to correct/handle cases where not, eg mac
	# or not installed. TODO
	strace_session = pexpect.spawn('strace -f -p $PID')
	pexpect.run('kill -CONT $PID')

	command_output = ''
	with curtsies.FullscreenWindow() as window:
		while True:
			# Setup
			wheight = window.height
			wwidth  = window.width
			a = curtsies.FSArray(wheight,wwidth)

			# Divide the screen up into two, to keep it simple for now
			wheight_top_end    = int(wheight / 2)
			wheight_bottom_start = int(wheight / 2) + 1

			header_text = 'telemetrise running on command: ' + command + ' ' + str(wheight) + 'x' + str(wwidth)
			a[0:1,0:len(header_text)] = [blue(header_text)]

			# a specs must match the length and width of the string
			# To render into window, use linesplit: linesplit(green(''.join(s.decode('latin-1') for s in self.received)), 80) if self.received else ['']

			# TODO: split per line and create a list of lines.
			# reverse the order

			if command_output != '':
				rendered_output = linesplit(''.join(s for s in command_output), wwidth_left_end)
				for i, line in zip(reversed(range(2,wheight_top_end)), reversed(rendered_output)):
					a[i:i+1, 0:len(line)] = [line]

			# We're done, now render!
			window.render_to_terminal(a)

			# Now read input from main spawn
			res = None
			try:
				res=pexpect_session.read_nonblocking(timeout=1)
			except pexpect.EOF:
				command_output += 'EOF'
			except:
				command_output += '?'
			if res:
				command_output += res.decode('utf-8')
				#outfile.write(command_output)
				#outfile.write('=====\n')
				#outfile.flush()

# TODO: unique the strace file
command = 'ping -c100 google.com'

outfile = open('outfile','w')

if __name__ == '__main__':
	main(command)
