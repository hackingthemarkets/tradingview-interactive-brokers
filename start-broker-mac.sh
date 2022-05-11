#!/bin/sh

logfile=broker.log

# start broker connection point
# this is in a while loop because sometimes the broker script crashes
while true; do
	echo --------------------------------- |tee -a $logfile
	date |tee -a $logfile
	echo Starting up |tee -a $logfile
	python3 -u broker.py 2>&1 |tee -a $logfile
	echo Restarting in 5s |tee -a $logfile
	sleep 5
done
