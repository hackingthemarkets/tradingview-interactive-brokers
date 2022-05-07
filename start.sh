#!/bin/sh

# make sure you've started the IB gateway or workstation before running this

# cleanup
for pid in `ps axuw |grep flask | grep -v grep | awk '{print $2}'`
	do kill $pid
done

# start webapp/webhook-receiver (move to port 6000 to get away from Mac airplay issues)
export FLASK_APP=webapp
export FLASK_ENV=development
flask run -p 6000 &

# start ngrok proxy -- requires paid account (or start in another window and use the generated hostname)
#ngrok http --subdomain=tvib-55683 6000 &

# start broker connection point
python3 broker.py
