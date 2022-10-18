#!/bin/sh

logfile=ngrok.log

# start ngrok proxy -- requires paid account if you want a fixed subdomain
subd=`grep ngrok-subdomain config.txt |awk '{print $3}'`
echo "Running while config.txt says 'ngrok-run = yes'"

while grep -s "ngrok-run = yes" config.txt >/dev/null ; do
	echo --------------------------------- |tee -a $logfile
	date |tee -a $logfile
	echo Starting up |tee -a $logfile
	if [ "$subd" = "" ] ; then
		ngrok http 6000
	else
		ngrok http --subdomain=$subd 6000
	fi
	echo Restarting in 5s |tee -a $logfile
	sleep 5
done

