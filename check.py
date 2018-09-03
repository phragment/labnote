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

import argparse
import contextlib
import io
import os
import re
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

    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        try:
            dtree = docutils.core.publish_doctree(rst)
        except docutils.utils.SystemMessage as e:
            dtree = None
            print("parsing failed", e)
    return err.getvalue(), dtree


rechar = u"\u02FD"
def handle_spaces(rstin):
    rstout = ""
    reg = re.compile("`.*<.* .*>`_")
    for line in rstin.splitlines():
        mat = reg.search(line)
        if mat:
            state = 0
            tl = ""
            for (i, c) in enumerate(line):
                if state == 0 and c == '`':
                    state = 1
                if state == 1 and c == '<':
                    state = 2
                if state == 2 and c == '`':
                    state = 0
                if state == 2 and c == ' ':
                    c = rechar
                tl += c
            line = tl
        rstout += line + "\n"
    return rstout


def handle_rst(f, cd, sd, verbose):

    filepath = os.path.join(cd, f)
    rst = None
    with open(filepath, "r") as fh:
        rst = fh.read()

    if not rst:
        print("file deleted since walk:", f)
        return []

    rst = handle_spaces(rst)
    (err, dtree) = rst2dtree(rst)
    if err and verbose:
        print("----------")
        print("error while parsing:", filepath)
        print("")
        print(err)
        print("")

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
        p = p.replace(rechar, " ")

        if not p:
            print("could not parse", ref)
            continue

        if not os.path.exists(p):
            print("")
            print(f)
            print("referenced file in line {} missing: {}".format(elem.parent.line, ref))
            print(p)
            continue

        refs.append(p)


    return refs



if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("path")
    args = parser.parse_args()
    dirpath = args.path

    print("==========")
    startdir = os.path.abspath(dirpath)
    print("checking:", startdir)

    os.chdir(startdir)

    refs = []
    nonrst = []
    rst = []

    for cd, subdirs, files in os.walk(startdir):

        if ".git" in cd:
            continue

        for f in files:

            if f == ".gitignore":
                continue

            if f.endswith(".rst"):
                r = handle_rst(f, cd, startdir, args.verbose)
                refs.extend(r)
                rst.append(os.path.join(cd, f))
            else:
                nonrst.append(os.path.join(cd, f))

    print("")
    print("stats")
    print("files", len(rst))
    print("references", len(refs))

    print("")
    print("rst not referenced:")
    for f in rst:
        if f not in refs:
            if f != startdir + "/index.rst":
                print(f)

    # check if all nonrst in refs
    print("")
    print("files not referenced:")
    for f in nonrst:
        if f not in refs:
            print(f)

    # search for TODO and FIXME
    print("")
    print("files containing TODO or FIXME:")
    for fp in rst:
        with open(fp, "r") as f:
            for (no, line) in enumerate(f):
                res = re.search("(TODO|FIXME)", line)
                if res:
                    #print(fp, "#", no, ":", line)
                    print("{} in line {}: {}".format(fp, no, line))

    print("")
    print("==========")


