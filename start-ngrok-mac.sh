#!/bin/sh

# start ngrok proxy -- requires paid account if you want a fixed subdomain
subd=`grep ngrok-subdomain config.txt |awk '{print $2}'`
if [ "$subd" = "" ] ; then
	ngrok http 6000
else
	ngrok http --subdomain=$subd 6000
fi
