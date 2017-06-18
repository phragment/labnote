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

import os
import os.path
import sys

import urllib
import urllib.request

# if i put the relative path lookup here
# -> think about the effective cwd!

def ref2uri_(ref, cwd=""):

    if "://" in ref:
        if not ref.startswith("file://"):
            return ""

        a = "ext"
        ref = ref[7:]
    else:
        a = "int"

    if os.path.isabs(ref):
        b = "abs"
        if sys.platform.startswith("lin"):
            ref = ref[1:]
    else:
        b = "rel"

    if sys.platform.startswith("win"):
        ref = urllib.request.pathname2url(ref)
    #ref = urllib.request.pathname2url(ref)

    uri = "file://labnote.{}.{}/{}".format(a, b, ref)

    return uri


def ref2uri(refuri, curdir, startdir):
    ## path to uri

    if "://" in refuri:
        if not refuri.startswith("file://"):
            return None

    if refuri.startswith("file://"):
        a = "ext"
        refuri = refuri[7:]
    else:
        a = "int"

    if refuri.startswith("/"):
        b = "abs"
        refuri = refuri[1:]
    else:
        b = "rel"

    if refuri.startswith("..") and b == "rel":
        if a == "int":
            refuri = curdir + "/" + refuri
            refuri = os.path.normpath(refuri)
            b = "abs"
        if a == "ext":
            refuri = startdir + "/" + refuri
            refuri = os.path.normpath(refuri)
            refuri = refuri[1:]
            b = "abs"

    refuri = "file://labnote.{}.{}/{}".format(a, b, refuri)
    return refuri

def uri2path(uri, curdir, startdir):
    ## uri to path
    uri_ = uri[23:]

    if uri[15:18] == "ext":
        ext = True
        if uri[19:22] == "rel":
            uri_ = startdir + "/" + uri_
        else:
            uri_ = "/" + uri_
    else:
        ext = False
        if uri[19:22] == "rel":
            if curdir:
                uri_ = curdir + "/" + uri_

    return uri_, ext


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


import unittest

class Tests(unittest.TestCase):

    # startdir absolute
    # curdir relative to startdir

    # switch to
    # rel
    # file://labnote.test/./
    # abs
    # file://labnote.test/

    def test_ref2uri_1(self):
        start = ""
        cur = ""
        ref = "index.rst"
        uri = "file://labnote.int.rel/index.rst"
        uri_ = ref2uri(ref, cur, start)
        self.assertEqual(uri, uri_)

    def test_ref2uri_2(self):
        start = ""
        cur = ""
        ref = "sub/index.rst"
        uri = "file://labnote.int.rel/sub/index.rst"
        uri_ = ref2uri(ref, cur, start)
        self.assertEqual(uri, uri_)

    def test_ref2uri_3(self):
        start = ""
        cur = ""
        ref = "/etc/resolv.conf"
        uri = "file://labnote.int.abs/etc/resolv.conf"
        uri_ = ref2uri(ref, cur, start)
        self.assertEqual(uri, uri_)

    def test_ref2uri_4(self):
        start = ""
        cur = ""
        ref = "file:///etc/resolv.conf"
        uri = "file://labnote.ext.abs/etc/resolv.conf"
        uri_ = ref2uri(ref, cur, start)
        self.assertEqual(uri, uri_)

    def test_ref2uri_5(self):
        start = ""
        cur = "sub"
        ref = "index.rst"
        uri = "file://labnote.int.rel/index.rst"
        uri_ = ref2uri(ref, cur, start)
        self.assertEqual(uri, uri_)

    def test_ref2uri_6(self):
        start = ""
        cur = "sub"
        ref = "../index.rst"
        uri = "file://labnote.int.abs/index.rst"
        uri_ = ref2uri(ref, cur, start)
        self.assertEqual(uri, uri_)

    def test_ref2uri_7(self):
        start = ""
        cur = "sub"
        ref = "../../index.rst"
        # TODO ???
        uri = "file://labnote.int.abs/../index.rst"
        uri_ = ref2uri(ref, cur, start)
        self.assertEqual(uri, uri_)


    def test_uri2path_1(self):
        start = ""
        cur = ""
        uri = "file://labnote.int.abs/index.rst"
        path = "index.rst"
        (path_, ext) = uri2path(uri, cur, start)
        self.assertEqual(path, path_)


    def test_ref2path_1(self):
        start = ""
        cur = ""
        ref = "sub/index.rst"
        (p1, ext) = uri2path(ref2uri(ref, cur, start), cur, start)
        p2 = ref2path(ref, cur, start)
        self.assertEqual(p1, p2)

    def test_ref2path_2(self):
        start = ""
        cur = "sub"
        ref = "sub/index.rst"
        (p1, ext) = uri2path(ref2uri(ref, cur, start), cur, start)
        p2 = ref2path(ref, cur, start)
        self.assertEqual(p1, p2)

    def test_ref2path_3(self):
        start = "/home/user/notes"
        cur = "sub"
        ref = "/index.rst"
        (p1, ext) = uri2path(ref2uri(ref, cur, start), cur, start)
        p2 = ref2path(ref, cur, start)
        self.assertEqual(p1, p2)

    def test_ref2path_4(self):
        start = "/home/user/notes"
        cur = "sub"
        ref = "/img/index.rst"
        (p1, ext) = uri2path(ref2uri(ref, cur, start), cur, start)
        p2 = ref2path(ref, cur, start)
        self.assertEqual(p1, p2)

    #@unittest.skipUnless(sys.platform.startswith("win"), "requires Windows")
    #def test_ref2uri_11(self):
    #    ref = "file://C:\pagefile.sys"
    #    uri = "file://labnote.ext.abs/C:/pagefile.sys"
    #    uri_ = ref2uri(ref)
    #    self.assertEqual(uri, uri_)

    #@unittest.skipUnless(sys.platform.startswith("win"), "requires Windows")
    #def test_ref2uri_12(self):
    #    ref = "sub\index.rst"
    #    uri = "file://labnote.int.rel/sub/index.rst"
    #    uri_ = ref2uri(ref)
    #    self.assertEqual(uri, uri_)

if __name__ == '__main__':
    #print(sys.platform)
    unittest.main()



