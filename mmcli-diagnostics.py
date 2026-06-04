#!/usr/bin/env python3

###
### 2023-12-06 | Authors: Leonardo Gurria
### The project is the automated process of running modem diagnostics on Linux using ModemManager
### License: hologram.io
###

import subprocess
import logging
import time
import json

# Sanity checks for ModemManager
def check_mmcli(log):
	# Check if mmcli is installed (should be installed by default)
	log.debug('Checking if mmcli is installed')
	installed = subprocess.getoutput('which mmcli')

	# Check if mmcli is running (should be running on boot)
	log.debug('Checking if mmcli is active and running')
	running = subprocess.getoutput('sudo systemctl status ModemManager')

	if len(installed) == 0 or 'active (running)' not in running:
		return False

	return True

# Sanity checks for debug mode
def check_debug_mode(log):
	# Check for service file
	log.debug('Checking if ModemManager.service file exists')
	service = subprocess.getoutput('ls -lrt /lib/systemd/system/ModemManager.service')

	if len(service) == 0:
		log.warning('File /lib/systemd/system/ModemManager.service does not exist')
		return False

	# Check for debug flag
	log.debug('Checking if debug flag is present')
	flag = subprocess.getoutput('grep "debug" /lib/systemd/system/ModemManager.service')

	if len(flag) == 0:
		log.debug('Debug flag is not present')
		return False

	return True

# Ask user how to proceed
def user_selection(log):
	# Print user menu
	print('\nDebug mode is not enabled on ModemManager')
	print('How would you like to proceed?')
	print('  0 - Basic Diagnostics')
	print('  1 - Show me how to enable it')
	user_input = int(input('Your selection: '))

	while user_input != 0 and user_input != 1:
		log.error('Please enter a valid option')
		user_input = int(input('Your selection: '))

	if user_input == 0:
		log.info('Proceeding with basic diagnostics! Please note this might take around 5 mins')
		# Do basic diagnostics
		b, p = basic_diagnostics(log)
		del p
		log.info(json.dumps(b, indent=4))
	else:
		log.debug('Showing instructions to enable debug mode')
		# Show instructions
		print('\nStep 1) Add --debug at the end of line: ExecStart=/usr/sbin/ModemManager in /lib/systemd/system/ModemManager.service file')
		print('  Line should look like this: ExecStart=/usr/sbin/ModemManager --debug')
		print('Step 2) Restart your RPi/Linux machine and run this script again!')
		exit(0)

# Basic diagnostics
def basic_diagnostics(log):
	# Check that modem is plugged in
	log.debug('Checking if modem is plugged in')
	plugged = subprocess.getoutput('mmcli -L')

	if 'No modems were found' in plugged:
		log.error('No modem is plugged in')
		exit(0)

	plugged = subprocess.getoutput('mmcli -L -J')
	plugged = json.loads(plugged)
	plugged = plugged['modem-list'][0]

	# Check for modem info
	log.debug('Checking for modem information in slot ' + plugged)
	modem = subprocess.getoutput('mmcli -m ' + plugged)

	if "error: couldn't find modem" in modem:
		log.error('Unable to check modem information')
		exit(0)

	log.debug(modem)
	# Get information on JSON format
	modem = subprocess.getoutput('mmcli -m ' + plugged + ' -J')
	log.debug('Modem JSON file')
	log.debug(modem)

	m = json.loads(modem)
	s = m['modem']['generic']['sim']
	b = m['modem']['generic']['bearers'][0] if len(m['modem']['generic']['bearers']) > 0 else 'No bearer'

	# Check that SIM is present
	log.debug('Checking for SIM in slot ' + s)
	sim = subprocess.getoutput('mmcli -i ' + s)

	if "error: couldn't find SIM" in sim:
		log.error('SIM is missing')
		exit(0)

	log.debug(sim)
	# Get information on JSON format
	sim = subprocess.getoutput('mmcli -i ' + s + ' -J')
	log.debug('SIM JSON file')
	log.debug(sim)

	# Check for bearer
	log.debug('Checking for connection in slot ' + b)
	bearer = subprocess.getoutput('mmcli -b ' + b)

	if "error: couldn't find bearer" in bearer or b == 'No bearer':
		log.warning('Connection is not in use')
		bearer = 'No bearer'
	else:
		log.debug(bearer)
		# Get information on JSON format
		bearer = subprocess.getoutput('mmcli -b ' + b + ' -J')
		log.debug('Bearer JSON file')
		log.debug(bearer)

	# Parse JSON information
	return parse_basic_diagnostics(log, modem, sim, bearer, plugged)

# Parse basic diagnsotics from JSON format
def parse_basic_diagnostics(log, modem, sim, bearer, plugged):
	log.debug('Basic Diagnostics')

	m = json.loads(modem)
	s = json.loads(sim)

	if bearer != 'No bearer':
		bea = json.loads(bearer)
		b = bea['bearer']['properties']['apn']
	else:
		b = bearer

	# Networks
	networks = subprocess.getoutput('sudo mmcli -m ' + plugged + ' --3gpp-scan --timeout=300 -J')

	if 'error' not in networks:
		net = json.loads(networks)
		n = net['modem']['3gpp']['scan-networks']
	else:
		n = networks
		log.warning(n)

	# Extended signal
	ext_signal = subprocess.getoutput('mmcli -m ' + plugged + ' --signal-get')
	ext_signal = ext_signal.replace('error rate threshold', '')

	if 'error' not in ext_signal:
		# Setup extended signal
		ext_signal = subprocess.getoutput('sudo mmcli -m ' + plugged + ' --signal-setup=10')
		# Wait 10 + 1 secs
		time.sleep(11)
		# Get actual extended signal
		ext_signal = subprocess.getoutput('mmcli -m ' + plugged + ' --signal-get -J')
		es = json.loads(ext_signal)

		if es['modem']['signal']['lte']['rssi'] == '--':
			log.debug('Fetching all RAT extended signal')
			sig = es['modem']['signal']
		else:
			log.debug('Fetching LTE extended signal')
			sig = es['modem']['signal']['lte']
	else:
		sig = ext_signal
		log.warning(f'Unable to get extended signal due to: {ext_signal}')

	basic_diagnostics = {
		'module': m['modem']['generic']['model'],
		'manufacturer': m['modem']['generic']['manufacturer'],
		'firmware': m['modem']['generic']['revision'],
		'iccid': s['sim']['properties']['iccid'],
		'signal': m['modem']['generic']['signal-quality'],
		'extended_signal': sig,
		'registration_status': m['modem']['generic']['state'] + ' | ' + m['modem']['3gpp']['registration-state'],
		'apn': b,
		'current_operator': m['modem']['3gpp']['operator-code'] + ' | ' + m['modem']['3gpp']['operator-name'],
		'networks_in_reach': n,
		'cpin': '',
		'fplmn': '',
		'csq': '',
		'cgact': '',
		'creg': '',
		'cgreg': '',
		'cereg': '',
		'cgdcont': ''
	}

	log.debug(json.dumps(basic_diagnostics, indent=4))

	return basic_diagnostics, plugged

# Full diagnostics
def full_diagnostics(log):
	# Run basic diagnsotics first
	full_diagnostics, plugged = basic_diagnostics(log)

	log.debug('Full diagnostics')

	# Run remaining commands for full diagnostics
	cpin = subprocess.getoutput("sudo mmcli -m " + plugged + " --command='+cpin?'")
	fplmn = subprocess.getoutput("sudo mmcli -m " + plugged + " --command='+crsm=176,28539,0,0,12'")
	csq = subprocess.getoutput("sudo mmcli -m " + plugged + " --command='+csq'")
	cgact = subprocess.getoutput("sudo mmcli -m " + plugged + " --command='+cgact?'")
	cgdcont = subprocess.getoutput("sudo mmcli -m " + plugged + " --command='+cgdcont?'")
	# These need to be checked in /var/log/syslog for their output
	creg = subprocess.getoutput("sudo mmcli -m " + plugged + " --command='+creg?'")
	# creg_out = subprocess.getoutput('cat /var/log/syslog | grep -i "+creg:" | tail -1')
	creg_out = subprocess.getoutput('journalctl -u ModemManager | grep -i "+creg:" | tail -1')
	cgreg = subprocess.getoutput("sudo mmcli -m " + plugged + " --command='+cgreg?'")
	# cgreg_out = subprocess.getoutput('cat /var/log/syslog | grep -i "+cgreg:" | tail -1')
	cgreg_out = subprocess.getoutput('journalctl -u ModemManager | grep -i "+cgreg:" | tail -1')
	cereg = subprocess.getoutput("sudo mmcli -m " + plugged + " --command='+cereg?'")
	# cereg_out = subprocess.getoutput('cat /var/log/syslog | grep -i "+cereg:" | tail -1')
	cereg_out = subprocess.getoutput('journalctl -u ModemManager | grep -i "+cereg:" | tail -1')

	# Sanity checks for outputs
	if 'error' in cpin or cpin == "response: ''":
		log.warning(f'Unable to run +cpin command due to: {cpin}')
	else:
		full_diagnostics['cpin'] = cpin

	if 'error' in fplmn or fplmn == "response: ''":
		log.warning(f'Unable to run +crsm command due to: {fplmn}')
	else:
		full_diagnostics['fplmn'] = fplmn

	if 'error' in csq or csq == "response: ''":
		log.warning(f'Unable to run +csq command due to: {csq}')
	else:
		full_diagnostics['csq'] = csq

	if 'error' in cgact or cgact == "response: ''":
		log.warning(f'Unable to run +cgact command due to: {cgact}')
	else:
		full_diagnostics['cgact'] = cgact

	if 'error' in cgdcont or cgdcont == "response: ''":
		log.warning(f'Unable to run +cgdcont command due to: {cgdcont}')
	else:
		full_diagnostics['cgdcont'] = cgdcont

	if 'error' in creg or len(creg_out) == 0:
		log.warning(f'Unable to run +creg command due to: {creg}')
	else:
		find = creg_out.find('<-- ')
		parse = creg_out[find:]
		full_diagnostics['creg'] = parse.replace('<-- ', '').replace("'", '').replace('<CR><LF>', '').replace('OK', '')

	if 'error' in cgreg or len(cgreg_out) == 0:
		log.warning(f'Unable to run +cgreg command due to: {cgreg}')
	else:
		find = cgreg_out.find('<-- ')
		parse = cgreg_out[find:]
		full_diagnostics['cgreg'] = parse.replace('<-- ', '').replace("'", '').replace('<CR><LF>', '').replace('OK', '')

	if 'error' in cereg or len(cereg_out) == 0:
		log.warning(f'Unable to run +cereg command due to: {cereg}')
	else:
		find = cereg_out.find('<-- ')
		parse = cereg_out[find:]
		full_diagnostics['cereg'] = parse.replace('<-- ', '').replace("'", '').replace('<CR><LF>', '').replace('OK', '')

	log.info(json.dumps(full_diagnostics, indent=4))

# Main
def main():
	# Measure execution time
	start_time = time.time()

	# Log info
	log = logging.getLogger('mmcli-diagnostics')
	logging.basicConfig(level=logging.DEBUG, filename='mmcli-diagnostics.log', filemode='w', format='%(asctime)s | %(name)s | %(levelname)s | %(message)s')
	# Console
	con = logging.StreamHandler()
	con.setLevel(logging.INFO)
	con.setFormatter(logging.Formatter('%(asctime)s | %(name)s | %(levelname)s | %(message)s'))
	log.addHandler(con)

	log.info('Starting script!')

	# Run sanity checks for ModemManager
	mmcli_ready = check_mmcli(log)

	if mmcli_ready is False:
		log.error('Your system does not have ModemManager ready for diagnostics')
		exit(0)

	# Run sanity checks for debug mode
	debug_mode_ready = check_debug_mode(log)

	if debug_mode_ready is False:
		log.debug('Debug mode is not enabled')

		# Check for user selection
		user_selection(log)
	else:
		log.info('Debug flag is present. Proceeding with full diagnostics! Please note this might take around 5 mins')
		full_diagnostics(log)

	log.info('Script completed!')
	
	# Measure execution time
	end_time = time.time()
	log.info('Execution duration: ' + str(end_time - start_time) + ' secs')

# Python stuff
if __name__ == '__main__':
	main()