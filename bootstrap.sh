#!/bin/sh
export FLASK_APP=./api/api.py
env\Scripts\Activate.ps1
flask --debug run -h 0.0.0.0