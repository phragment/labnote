#!/usr/bin/env python3

import docutils
import docutils.core
import re

# http://docutils.sourceforge.net/docs/ref/rst/restructuredtext.html#reference-names
# Simple reference names are single words consisting of alphanumerics
# plus isolated (no two adjacent) internal hyphens, underscores, periods, colons and plus signs;
# no whitespace or other characters are allowed.

# some hyperlink references use the simple reference name syntax.

rst = """
minimal example

`test </tmp/foo bar>`__

test `test </tmp/foo bar>`_ test

"""

rst_ = ""
reg = re.compile("`.*<.* .*>`_")
for line in rst.splitlines():
    mat = reg.search(line)
    if mat:
        print(mat)

        state = 0
        fuck = ""
        for (i, c) in enumerate(line):
            if state == 0 and c == '`':
                state = 1
            if state == 1 and c == '<':
                state = 2
            if state == 2 and c == '`':
                state = 0
            if state == 2 and c == ' ':
                c = u"\u2000"
            fuck += c

        print(fuck)
        line = fuck

    rst_ += line + "\n"


print(rst_)


dtree = docutils.core.publish_doctree(rst)

#print(dtree)

html = docutils.core.publish_from_doctree(dtree, writer_name="html4css1")

"""
<body>
<div class="document">
<p>minimal example</p>
<p><a class="reference external" href="/tmp/foobar">test</a></p>
</div>
</body>
"""
#print(html.decode())


