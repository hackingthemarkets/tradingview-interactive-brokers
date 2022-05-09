#!/bin/sh

# start broker connection point
python3 broker.py 2>&1 |tee -a broker.log
