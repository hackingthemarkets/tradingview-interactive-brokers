#!/bin/sh

logfile=broker.log

alpacakey=`grep alpaca-key config.txt |awk '{print $2}'`
alpacasecret=`grep alpaca-secret config.txt |awk '{print $2}'`

# start broker connection point
# this is in a while loop because sometimes the broker script crashes
while true; do
	echo --------------------------------- |tee -a $logfile
	date |tee -a $logfile
	echo Starting up |tee -a $logfile
	python3 -u broker-alpaca.py $alpacakey $alpacasecret 2>&1 |tee -a $logfile
	echo Restarting in 5s |tee -a $logfile
	sleep 5
done
