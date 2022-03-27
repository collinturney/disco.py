#!/bin/bash

if [ $# != 1 ]; then
    echo "Usage: $0 SVC_FILE"
    exit 1
fi

SVC=$1

sudo mv $SVC /lib/systemd/system/
sudo chmod 644 /lib/systemd/system/$SVC
sudo systemctl daemon-reload
sudo systemctl enable $SVC
sudo systemctl start  $SVC
sudo systemctl status $SVC
