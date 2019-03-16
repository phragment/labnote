#!/bin/sh

sudo install -Dm755 labnote.py /usr/local/bin/labnote
sudo -k

mkdir -p ~/.config/labnote
cp config/* ~/.config/labnote/

install -Dm644 labnote.desktop ~/.local/share/applications/labnote.desktop
update-desktop-database ~/.local/share/applications/

