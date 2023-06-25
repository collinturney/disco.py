#!/bin/bash -ex

if [ $# != 1 ]; then
    echo "Usage: $0 SVC_FILE"
    exit 1
fi

SVC=$1

sudo mkdir -p /opt/bin/
sudo cp -p *.py /opt/bin/
sudo cp $SVC /lib/systemd/system/
sudo chmod 644 /lib/systemd/system/$SVC
sudo systemctl daemon-reload
sudo systemctl enable $SVC
sudo systemctl start  $SVC
sudo systemctl status $SVC
