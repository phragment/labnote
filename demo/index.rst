
Welcome to Labnote
==================

Intro
-----

**LabNote** uses *reStructuredText* to help you write, organize and browse your notes, reports or
knowledge collections.

Basically its a desktop wiki based on a folder with a bunch of text files.


Features
--------

LabNote is basically a simple Markup editor with live preview for rST.
As such it has no special syntax or file headers.

`rST examples <directives.rst>`__

But it offers unique features such as links between rST files, which you can
follow from the fast *live preview*.

`Links <links/index.rst>`__ can lead between directory hierarchies.

LabNote provides useful `Shortcuts <shortcuts.rst>`__.


Git
```

LabNote supports versioning.
Simply run **git init** in your notes folder LabNote will automatically
commit changes upon changing between files and pushed upon exit.


rST Demos
---------

`<docutils/index.rst>`__


References
----------

reStructuredText references by the Docutils project, the creators of rST:

`Quick Reference <http://docutils.sourceforge.net/docs/user/rst/quickref.html>`__

`Markup Specification <http://docutils.sourceforge.net/docs/ref/rst/restructuredtext.html>`__

There is also a reference by the Sphinx project, a documentation generator for
Python code which employs rST:

`Primer <http://www.sphinx-doc.org/en/stable/rest.html>`__


Internals
---------

LabNote uses:

- `PyGObject <https://pygobject.readthedocs.io/en/latest/>`__
- `GtkSourceView <https://wiki.gnome.org/Projects/GtkSourceView>`__
- `Docutils <http://docutils.sourceforge.net/>`__
- `WebKit2Gtk+ <https://webkitgtk.org/>`__

