#!/usr/bin/env python3

# Copyright 2017 Thomas Krug
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import contextlib
import io
import os
import sys

import docutils
import docutils.core
import docutils.utils


def ref2path(ref, curdir, startdir):

    if "://" in ref:
        if not ref.startswith("file://"):
            return None

    if ref.startswith("file://"):
        ref = ref[7:]
        if os.path.isabs(ref):
            path = ref
        else:
            path = os.path.join(startdir, ref)
    else:
        if os.path.isabs(ref):
            ref = ref[1:]
            path = os.path.join(startdir, ref)
        else:
            path = os.path.join(startdir, curdir, ref)

    path = os.path.normpath(path)

    return path


def rst2dtree(rst):
    null = io.StringIO()
    with contextlib.redirect_stderr(null):
        try:
            dtree = docutils.core.publish_doctree(rst)
        except docutils.utils.SystemMessage as e:
            dtree = None
    return dtree

def handle_rst(f, cd, sd):

    rst = None
    with open(os.path.join(cd, f), "r") as fh:
        rst = fh.read()

    if not rst:
        print("file deleted since walk:", f)
        return []

    dtree = rst2dtree(rst)

    if not dtree:
        print("error parsing file:", f)
        return []


    refs = []
    for elem in dtree.traverse(siblings=True):
        ref = None
        if elem.tagname == "reference":
            ref = elem.get("refuri")
        if elem.tagname == "image":
            ref = elem.get("uri")

        if not ref:
            continue


        ignore = ["http://", "https://", "ftp://", "ftps://", "mailto:", "nfs://", "ldap://", "about:"]

        for ign in ignore:
            if ref.startswith(ign):
                ref = None
                break
        if not ref:
            continue


        p = ref2path(ref, cd, sd)

        if not p:
            print("could not parse", ref)
            continue

        # TODO give line numbers for references
        if not os.path.exists(p):
            print("")
            print(f)
            print("referenced file missing:", ref)
            print(p)
            continue

        refs.append(p)


    return refs



if __name__ == "__main__":

    startdir = os.path.abspath(sys.argv[1])
    print("checking:", startdir)

    os.chdir(startdir)

    refs = []
    nonrst = []
    rst = []

    for cd, subdirs, files in os.walk(startdir):

        #print("")
        #print(cd, subdirs, files)

        if ".git" in cd:
            continue

        for f in files:

            if f == ".gitignore":
                continue

            if f.endswith(".rst"):
                r = handle_rst(f, cd, startdir)
                refs.extend(r)
                rst.append(os.path.join(cd, f))
            else:
                nonrst.append(os.path.join(cd, f))

    print("")
    print("rst not referenced:")
    for f in rst:
        if f not in refs:
            print(f)

    # check if all nonrst in refs
    print("")
    print("files not referenced:")
    for f in nonrst:
        if f not in refs:
            print(f)

