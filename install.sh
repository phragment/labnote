#!/bin/sh

sudo cp labnote.py /usr/local/bin/labnote
sudo chmod +x /usr/local/bin/labnote

sudo -k

mkdir -p ~/.config/labnote
cp config/* ~/.config/labnote/

cp labnote.desktop ~/.local/share/applications/
update-desktop-database ~/.local/share/applications/

