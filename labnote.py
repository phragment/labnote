#!/usr/bin/env python3

# Copyright 2016-2017 Thomas Krug
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
import configparser
import contextlib
import datetime
import io
import logging
import mimetypes
import os
import random
import re
import signal
import string
import subprocess
import sys
import tempfile
import time
import urllib
import urllib.request
from urllib.parse import urlparse

# python-gobject
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GObject, Gtk, Pango, Gdk, GdkPixbuf, GLib, Gio

# webkit2gtk
gi.require_version('WebKit2', '4.0')
from gi.repository import WebKit2

# gtksourceview3
gi.require_version('GtkSource', '3.0')
from gi.repository import GtkSource

# python-docutils
#   python-pygments (code highlighting)
import docutils
import docutils.core

# TODO
# - GtkShortcutsWindow ???
#  Ctrl+? and Ctrl+F1
#  - menu + accels?
# - config file handling
# - stylesheet handling & paths
# - use os.path consequently

# git integration
#  - commit on file switch (done)
#  - add after new file saved (done)
#  - push before exit (done)
#  - get revision pdf export (done)

class mainwindow():

    def __init__(self, source_view_scheme, stylesheet, right_side_editor, git):

        self.source_view_scheme = source_view_scheme
        self.stylesheet = stylesheet
        self.right_side_editor = right_side_editor
        self.git = git

        self.load_state = 0
        self.ignore_modified = False
        self.lock_line = 0

        self.current_file = ""

        self.history_home = ""
        self.history_stack = []
        self.history_ignore = False


        self.window = Gtk.Window()
        self.window.connect("delete-event", self.on_delete_event)
        self.window.connect("key-press-event", self.on_key_press_event)
        self.window.set_title("LabNote")
        self.window.set_wmclass("default", "LabNote")

        # set icon
        icon_theme = Gtk.IconTheme.get_default()
        icon = Gio.ThemedIcon.new_with_default_fallbacks("text-x-generic-symbolic")
        icon_list = []
        for size in (24, 48, 96, 256):
            icon_info = icon_theme.lookup_by_gicon(icon, size, 0)
            icon_image = Gtk.Image.new_from_pixbuf(icon_info.load_icon())
            icon_list.append(icon_image.props.pixbuf)
        self.window.set_default_icon_list(icon_list)

        # size & position
        screen = self.window.get_screen()
        win = screen.get_active_window()
        if win:
            mon = screen.get_monitor_at_window(win)
            window_rect = screen.get_monitor_geometry(mon)
        else:
            window_rect = screen.get_monitor_geometry(0)

        width  = window_rect.width  * 0.75
        height = window_rect.height * 0.75
        self.window.set_size_request(int(width), int(height))

        self.window.set_position(Gtk.WindowPosition.CENTER)


        ##
        vbox = Gtk.VBox(False, 0)
        self.window.add(vbox)


        tb_back = Gtk.Button()
        icon = Gio.ThemedIcon.new_with_default_fallbacks("go-previous-symbolic")
        img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.SMALL_TOOLBAR)
        tb_back.add(img)
        tb_back.connect("clicked", self.go_back)


        toolbox = Gtk.HBox(False, 0)

        self.entry = Gtk.Entry()
        self.entry.connect("activate", self.on_entry_act)

        toolbox.pack_start(tb_back, False, False, 0)
        toolbox.pack_start(self.entry, True, True, 0)

        vbox.pack_start(toolbox, False, False, 0)


        scrolledwindow = Gtk.ScrolledWindow()
        scrolledwindow.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        # sourceview
        self.textview = GtkSource.View()
        self.textview.modify_font(Pango.FontDescription("DejaVu Sans Mono Book 10"))
        self.textview.set_tab_width(2)
        self.textview.set_insert_spaces_instead_of_tabs(True)
        self.textview.set_show_line_numbers(True)
        self.textview.set_auto_indent(True)
        self.textview.set_smart_home_end(True)
        self.tvbuffer = self.textview.get_buffer()
        self.tvbuffer.props.language = GtkSource.LanguageManager.get_default().get_language('rst')
        self.tvbuffer.props.style_scheme = GtkSource.StyleSchemeManager.get_default().get_scheme(source_view_scheme)

        #self.tvbuffer.connect("insert-text", self.tvbuffer_on_insert_text)
        #self.tvbuffer.connect("paste-done", self.tvbuffer_on_paste_done)

        self.textview.connect("button-release-event", self.on_button_event)
        self.textview.connect("size-allocate", self.textview_on_size_allocate)

        scrolledwindow.add(self.textview)


        hbox2 = Gtk.HBox(True, 0)

        settings = WebKit2.Settings()
        settings.set_enable_javascript(True)

        #
        settings.set_enable_java(False)
        # flash, pipelight, etc.
        settings.set_enable_plugins(False)
        settings.set_enable_page_cache(False)
        #
        settings.set_enable_webaudio(False)
        settings.set_enable_webgl(False)
        # "MediaStream is an experimental proposal for allowing
        # web pages to access audio and video devices for capture."
        settings.set_enable_media_stream(False)
        # "MediaSource is an experimental proposal which extends
        # HTMLMediaElement to allow JavaScript to generate media
        # streams for playback."
        settings.set_enable_mediasource(False)

        settings.set_default_font_family("DejaVu Sans")
        settings.set_default_font_size(14)
        settings.set_minimum_font_size(12)

        self.webview = WebKit2.WebView.new_with_settings(settings)

        context = self.webview.get_context()
        context.register_uri_scheme("file", self.uri_scheme_file)
        context.set_cache_model(WebKit2.CacheModel.DOCUMENT_VIEWER)
        context.clear_cache()

        self.webview.connect("decide-policy", self.load_policy)
        self.webview.connect("context-menu", self.disable_context_menu)
        self.webview.connect("load-changed", self.load_changed)
        self.webview.connect("button-release-event", self.on_button_event)
        # debug
        self.webview.connect("load-failed", self.load_failed)


        ##
        self.search_results = Gtk.ListStore(str, str, str)
        self.treeview = Gtk.TreeView(model=self.search_results)
        self.treeview.set_headers_visible(False)

        columns = ["filepath", "line", "lineno"]
        for i in range(len(columns)):
            cell = Gtk.CellRendererText()
            col = Gtk.TreeViewColumn(columns[i], cell, text=i)
            col.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
            if i == 0:
                col.set_alignment(1.0)
            self.treeview.append_column(col)

        self.treeview.connect("row-activated", self.on_search_result)
        self.treeview.connect("key-press-event", self.on_search_key)

        self.search_results_sw = Gtk.ScrolledWindow()
        self.search_results_sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.search_results_sw.add(self.treeview)

        # homogeneous, spacing
        hbox = Gtk.HBox(True, 0)
        if self.right_side_editor:
            # expand, fill, padding
            hbox.pack_start(self.search_results_sw, False, True, 0)
            hbox.pack_start(self.webview, True, True, 1)
            hbox.pack_start(scrolledwindow, True, True, 1)
        else:
            hbox.pack_start(scrolledwindow, True, True, 1)
            hbox.pack_start(self.webview, True, True, 1)
            hbox.pack_start(self.search_results_sw, False, True, 0)
        vbox.pack_start(hbox, True, True, 0)

        # search
        self.search = Gtk.SearchEntry()
        self.search.connect("activate", self.on_search)
        self.search.connect("key-press-event", self.on_search_key)

        self.searchr = Gtk.Revealer()
        self.searchr.add(self.search)

        vbox.pack_start(self.searchr, False, False, 0)


        self.info = Gtk.Revealer()
        vbox.pack_start(self.info, False, False, 2)
        info_box = Gtk.HBox(False, 0)
        self.info.add(info_box)
        info_box_label = Gtk.Label("No write since last change. Proceed?")
        info_box.pack_start(info_box_label, False, False, 3)
        self.info_box_button_ok = Gtk.Button()
        self.info_box_button_ok.set_label("   OK   ")
        self.info_box_button_ok.connect("clicked", self.info_box_button_ok_clicked)
        info_box.pack_end(self.info_box_button_ok, False, False, 3)
        info_box_button_cancel = Gtk.Button()
        info_box_button_cancel.set_label(" Cancel ")
        info_box_button_cancel.connect("clicked", self.info_box_button_cancel_clicked)
        info_box.pack_end(info_box_button_cancel, False, False, 0)


        statusbar = Gtk.HBox(False, 0)
        vbox.pack_start(statusbar, False, False, 0)

        self.state = Gtk.Label()
        space = Gtk.Label()
        statusbar.pack_start(space, True, True, 0)
        statusbar.pack_start(self.state, False, False, 3)

        self.textview.get_buffer().connect("changed", self.buffer_changed)

        vbox.show_all()
        self.window.show()
        self.search_results_sw.hide()
        self.textview.grab_focus()


    def tvbuffer_on_insert_text(self, textbuffer, textiter, text, length):

        print(textbuffer)
        print(textiter)
        print(text)
        print(length)

    def tvbuffer_on_paste_done(self, textbuffer, clipboard):

        print(textbuffer)
        print(clipboard)        

    def textview_on_size_allocate(self, widget, allocation):

        if self.lock_line:
            it = self.tvbuffer.get_iter_at_line(self.lock_line)
            self.textview.scroll_to_iter(it, 0, True, 0.0, 0.0)

    def info_box_button_ok_clicked(self, widget):
        self.tvbuffer.set_modified(False)
        self.webview.load_uri(self.saved_request)
        self.info.set_reveal_child(False)


    def info_box_button_cancel_clicked(self, widget):
        self.info.set_reveal_child(False)


    def on_button_event(self, widget, event):
        (foo, button) = event.get_button()

        if button == 8:
            self.go_back()
            return True
        if button == 9:
            pass

        return False


    def on_search_key(self, widget, event):

        if event.keyval == Gdk.KEY_Escape:
            self.lock_line = 0
            self.searchr.set_reveal_child(False)
            self.search_results_sw.hide()
            self.webview.show()


    # search result activated
    def on_search_result(self, treeview, it, path):

        selection = treeview.get_selection()
        (model, pathlist) = selection.get_selected_rows()
        it = model.get_iter(pathlist[0])
        res_file = model.get_value(it, 1)
        res_line = int(model.get_value(it, 0)) - 1


        if self.search_mode == "global":
            # tvbuffer is updated by callback function below

            self.ignore_modified = True
            self.lock_line = res_line

            window.webview.load_uri("file://" + res_file)

        if self.search_mode == "local":
            it_ = self.tvbuffer.get_iter_at_line(res_line)
            self.textview.scroll_to_iter(it_, 0, True, 0.0, 0.0)

            self.ignore_modified = True
            self.lock_line = res_line

            window.webview.load_uri("file://" + self.current_file)


    def on_key_press_event(self, widget, event):

        # Ctrl
        #if event.state == Gdk.ModifierType.CONTROL_MASK:
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            if event.keyval == ord("s"):
                log.debug("saving " + self.current_file)

                self.state.set_label("saving...")

                #
                if self.git:
                    if not os.path.exists(self.current_file):
                        gitadd = True
                    else:
                        gitadd = False

                filedir = os.path.dirname(self.current_file)
                if filedir:
                    if not os.path.exists(filedir):
                        os.makedirs(filedir)

                # write-replace (unix style)
                tmpfile = "." + os.path.basename(self.current_file) + ".swp"
                tmpfile = os.path.join(filedir, *[tmpfile])
                log.debug("tmpfile " + tmpfile)

                try:
                    fd = os.open(tmpfile, os.O_WRONLY | os.O_CREAT| os.O_EXCL, 0o600)
                except FileExistsError:
                    self.state.set_label("could not save!")
                    return
                with os.fdopen(fd, "w") as f:
                    f.write(self.tvbuffer.props.text)
                os.rename(tmpfile, self.current_file)

                self.tvbuffer.set_modified(False)
                self.state.set_label("saved")

                # git, add on new file saved
                if self.git:
                    if gitadd:
                        log.debug("new file saved, going to add file")
                        (ret, msg) = run(["git", "add", self.current_file])
                        log.debug(msg)

                return True

            if event.keyval == ord("l"):
                self.entry.grab_focus()

            if event.keyval == ord("f"):
                self.search_mode = "local"
                self.search.set_placeholder_text("search in file")
                self.searchr.set_reveal_child(True)
                # this should wait for revealer animation to finish
                self.search.grab_focus()

        # Ctrl Shift
        #if event.state == (Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK):

            if event.keyval == ord("F"):
                self.search_mode = "global"
                self.search.set_placeholder_text("search over files")
                self.searchr.set_reveal_child(True)
                self.search.grab_focus()

            if event.keyval == ord("E"):
                log.debug("start export")

                title = self.current_file.replace("_", "\_")
                if self.git:
                    rev = git_get_rev(self.current_file)
                else:
                    rev = ""
                dt = datetime.datetime.now().strftime("%Y-%m-%d")

                preamble  = "\\usepackage[left=2cm,right=1cm,top=1.5cm,bottom=1.5cm,includeheadfoot]{geometry}\n"
                preamble += "\\usepackage{parskip}\n"
                preamble += "\\usepackage{lmodern}\n"
                preamble += "\\usepackage{fancyhdr}\n"
                preamble += "\\fancyhf{}\n"
                preamble += "\\fancyhead[L]{" + title + "}\n"
                preamble += "\\fancyhead[R]{\\thepage}\n"
                preamble += "\\fancyfoot[L]{" + rev + "}\n"
                preamble += "\\fancyfoot[R]{" + dt + "}\n"
                preamble += "\\pagestyle{fancy}\n"
                preamble += "\\makeatletter\n"
                preamble += "\\let\\ps@plain\\ps@fancy\n"
                preamble += "\\usepackage[pdftex]{graphicx}\n"
                preamble += "\\setkeys{Gin}{width=0.8\\textwidth,height=0.3\\textheight,keepaspectratio}\n"

                args = {"latex_preamble": preamble}

                rst = self.tvbuffer.props.text

                try:
                    # http://docutils.sourceforge.net/docs/user/config.html#latex2e-writer
                    # http://docutils.sourceforge.net/docs/user/latex.html
                    latex = docutils.core.publish_string(rst, writer_name='latex', settings=None, settings_overrides=args)
                except NotImplementedError:
                    log.error("could not convert to latex")
                    return True
                latex = latex.decode()
                with tempfile.TemporaryDirectory(prefix="labnote-") as tmpdir:
                    # copy whole current dir contents to tmpdir, kind of hacky
                    curdir = os.path.dirname(self.current_file)
                    curdir = os.path.join(startdir, curdir)
                    run(["bash", "-c", "cp " + curdir + "/* " + tmpdir])

                    with open(os.path.join(tmpdir, "labnote.tex"), "w") as f:
                        f.write(latex)
                    (ret, out) = run(["pdflatex", "-halt-on-error", "labnote.tex"], cwd=tmpdir)
                    if ret != 0:
                        log.error("latex failed")
                        log.debug(out)
                        print(out)
                        return True
                    if "Rerun" in out or "rerunfilecheck" in out:
                        log.debug("second latex run")
                        (ret, out) = run(["pdflatex", "-halt-on-error", "labnote.tex"], cwd=tmpdir)
                    run(["mv", "labnote.pdf", "/tmp/"], cwd=tmpdir)
                    # debug
                    #run(["mv", "labnote.tex", "/tmp/"], cwd=tmpdir)

                subprocess.call(["xdg-open", "/tmp/labnote.pdf"])
                log.debug("export done")
                return True

            if event.keyval == ord("V"):

                clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
                text = clipboard.wait_for_text()

                if not text:
                    return True

                text_ = ""
                for line in text.splitlines():
                    text_ += "  " + line + "\n"

                self.tvbuffer.insert_at_cursor(text_)

                return True

        # Alt
        #if event.state == Gdk.ModifierType.MOD1_MASK:
        if event.state & Gdk.ModifierType.MOD1_MASK:

            if event.keyval == Gdk.KEY_Left:
                log.debug("go back")
                self.go_back()
                return True

            if event.keyval == Gdk.KEY_Up:
                log.debug("go home")
                window.webview.load_uri("file://" + self.history_home)
                return True

        return False


    def load_failed(self, view, event, failing_uri, error):
        log.debug("")
        log.debug("load failed " + failing_uri + " " + str(error))
        log.debug("")
        return True


    def load_changed(self, view, event):
        if event == WebKit2.LoadEvent.STARTED:
            self.load_state = 0
        if event == WebKit2.LoadEvent.COMMITTED:
            self.load_state = 1
        if event == WebKit2.LoadEvent.FINISHED:
            self.load_state = 2
            self.ignore_modified = False
            log.debug("load finished")
            log.debug("----------")


    def disable_context_menu(self, view, menu, event, hittestresult):
        return True


    def load_policy(self, webview, decision, decision_type):
        uri = urlparse( decision.get_request().get_uri() )

        if not uri.scheme == "file":
            decision.ignore()

        extern = ["http", "https", "ftp", "ftps", "mailto"]

        if uri.scheme in extern:
            subprocess.call(["/usr/bin/xdg-open", uri.geturl()])

        return True


    def uri_scheme_file(self, request):
        #self.state.set_label("loading")

        uri = request.get_uri()
        log.debug("----------")
        log.debug("loading")
        log.debug("URI " + uri)
        log.debug("state " + str(self.load_state))

        path_ = request.get_path()
        log.debug("path " + path_)

        # handle spaces in links
        uri = urllib.request.unquote(uri)
        uri = uri.replace(rechar, " ")

        ## sanitize
        # remove file://
        uri = uri[7:]
        # normalize
        uri = os.path.normpath(uri)
        log.debug("URI " + uri)

        # index.rst/rst/demo.rst
        # index.rst/rst/images/biohazard.png

        # is there a better solution?
        uri_ = uri.split("/")
        if len(uri_) > 1:
            if ".rst" in uri_[0]:
                # file://index.rst/rst/images/biohazard.png
                uri = "/".join(uri_[1:])
            else:
                # file://rst/images/biohazard.png
                log.error("file URLs are buggy")
        log.debug("URI " + uri)


        if uri.endswith(".rst"):

            if self.tvbuffer.get_modified() and not self.ignore_modified:
                log.debug("cancel due to modified")
                err = GLib.Error("load cancelled: open file modified")
                request.finish_error(err)

                self.saved_request = request.get_uri()

                self.info.set_reveal_child(True)
                self.info_box_button_ok.grab_focus()
                return

            self.load_rst(uri, request)
            self.state.set_label("loaded")
            return

        if self.load_state == 1:
            (typ, enc) = mimetypes.guess_type(uri)
            log.debug(typ)
            if typ and typ.startswith("image"):
                self.load_img(uri, request)
            return

        if self.load_state == 0:
            self.open_file(uri, request)

            err = GLib.Error("load cancelled: file opened externally")
            request.finish_error(err)

            return


    def open_file(self, uri, request):
        log.debug("open file: " + uri)
        subprocess.call(["/usr/bin/xdg-open", uri])


    def load_img(self, uri, request):
        log.debug("load image " + uri)
        try:
            f = Gio.file_parse_name(uri)
            stream = Gio.file_new_for_path(uri).read()
            request.finish(stream, -1, None)
        except GLib.Error:
            stream = Gio.MemoryInputStream.new_from_data("file not found".encode())
            request.finish(stream, -1, None)


    def load_rst(self, uri, request):
        log.debug("load text")

        ## history
        if not self.history_ignore:
            if self.current_file:
                try:
                    if self.history_stack[-1] != self.current_file:
                        self.history_stack.append(self.current_file)
                except IndexError:
                        self.history_stack.append(self.current_file)
        else:
            self.history_ignore = False
        log.debug("history\n" + str(self.history_stack))


        ## git, commit on file switch
        if self.git:
            if self.current_file:
                log.debug("committing changes due to file switch")
                # git commit --allow-empty-message -m '' foo.rst
                #(ret, msg) = run(["git", "commit", "--allow-empty-message", "-m", "", self.current_file])
                (ret, msg) = run(["git", "commit", "-a", "--allow-empty-message", "-m", ""])
                log.debug(msg)


        self.current_file = uri
        log.debug("current file URI " + uri)

        self.entry.set_text(uri)

        # get contents
        try:
            f = open(uri, "r")
            txt = f.read()
            f.close()
        except FileNotFoundError:
            # new file
            txt = ""

        self.tvbuffer.handler_block_by_func(self.buffer_changed)
        self.tvbuffer.begin_not_undoable_action()
        self.tvbuffer.set_text(txt)
        self.tvbuffer.end_not_undoable_action()
        self.tvbuffer.set_modified(False)
        self.tvbuffer.handler_unblock_by_func(self.buffer_changed)

        html = self.render(txt)

        html = html.encode("latin-1", errors="xmlcharrefreplace")

        stream = Gio.MemoryInputStream.new_from_data(html)
        request.finish(stream, -1, None)


    def buffer_changed(self, textbuf):
        self.state.set_label("modified")

        rst = textbuf.props.text

        html = self.render(rst, lock=True)

        base = os.path.basename(self.current_file) + "/" + os.path.dirname(self.current_file)
        base = os.path.normpath(base)
        base = "file://" + base + "/"
        log.debug("base " + base)
        self.ignore_modified = True
        self.webview.load_html(html, base)


    def go_back(self, widget=None):
        if len(self.history_stack):
            self.history_ignore = True
            #self.webview.load_uri("file://" + self.history_stack[-1])
            self.webview.load_uri("file://dummy.rst/" + self.history_stack[-1])
            del self.history_stack[-1]


    # load file (location bar)
    def on_entry_act(self, entry):
        self.webview.load_uri("file://" + entry.get_text())


    # starting search
    def on_search(self, entry):
        pattern = entry.get_text()
        if not pattern:
            return

        self.search_results.clear()

        if self.search_mode == "global":
            #path = os.path.dirname(self.current_file)
            #if not path:
            #    path = "./"
            #res = grep(pattern, path)
            res = grep(pattern, startdir)

            for r in res:
                self.search_results.append(r)

        if self.search_mode == "local":
            res = search(pattern, self.current_file)

            for r in res:
                self.search_results.append(r)

            if res:
                it = self.tvbuffer.get_iter_at_line(int(res[0][0])-1)
                self.textview.scroll_to_iter(it, 0, True, 0.0, 0.0)

        self.webview.hide()
        self.search_results_sw.show()


    def on_delete_event(self, widget, event):

        self.shutdown()

    def shutdown(self):

        log.debug("exiting")

        self.webview.run_javascript("window.close()", None, None)

        #
        if self.git:
            (ret, msg) = run(["git", "ls-remote"])
            log.debug(msg)
            # no remotes 128
            if ret == 0:
                (ret, msg) = run(["git", "push"])
                log.debug(msg)

        loop.quit()


    def render(self, rst, lock=False):

        a = time.time()

        rst = handle_spaces(rst)

        if self.stylesheet == "":
            args = {'embed_stylesheet': True}
        else:
            args = {
                    'stylesheet_path': '',
                    'stylesheet': self.stylesheet,
                    'embed_stylesheet': True
                }

        if lock or self.lock_line:
            # get current line
            cursor_mark = self.tvbuffer.get_insert()
            cursor_iter = self.tvbuffer.get_iter_at_mark(cursor_mark)
            line = cursor_iter.get_line()
            if not line:
                line = 0

            if self.lock_line:
                line = self.lock_line

            mark = "<a id='btj0m1ve'></a>"
            node_mark = docutils.nodes.raw(mark, mark, format="html")

        null = io.StringIO()
        with contextlib.redirect_stderr(null):
            try:
                dtree = docutils.core.publish_doctree(rst)
            except docutils.utils.SystemMessage as e:
                return "<body>Error<br>" + str(e) + "</body>"

        if lock or self.lock_line:
            prev = []
            for elem in dtree.traverse(siblings=True):
                if elem.line:
                    if elem.line >= line:
                        break
                    prev.append(elem)
            blacklist = ["math_block"]
            for elem in reversed(prev):
                if elem.tagname in blacklist:
                    continue
                else:
                    log.debug("insert mark into " + elem.tagname)
                    elem.insert(0, node_mark)
                    break

            # more debug
            if log.getEffectiveLevel() < logging.ERROR:
                pretty = docutils.core.publish_from_doctree(dtree, writer_name="pseudoxml")

                with open("/tmp/labnote.dtree", "w") as f:
                    f.write(pretty.decode())

        with contextlib.redirect_stderr(null):
            try:
                html = docutils.core.publish_from_doctree(dtree, writer_name="html4css1", settings=None, settings_overrides=args)
                html = html.decode()
            except docutils.utils.SystemMessage as e:
                html = "<body>Error<br>" + str(e) + "</body>"

        if lock or self.lock_line:
            body = '<body onload="scroll()">'
            html = re.sub(r'<body>', body, html, re.M)

            script = "<head><script>function scroll() {document.getElementById('btj0m1ve').scrollIntoView();}</script>"
            html = re.sub(r'<head>', script, html, re.M)

        # debug output
        if log.getEffectiveLevel() < logging.ERROR:
            with open("/tmp/labnote.html", "w") as f:
                f.write(html)

        b = time.time()
        if log.getEffectiveLevel() < logging.ERROR:
            log.info("load time " + str(b - a))

        return html


def search(pattern, filepath):
    r = re.compile(pattern, flags=re.IGNORECASE)
    res = []
    with open(filepath) as f:
        for (lineno, line) in enumerate(f):
            if r.search(line):
                res.append([str(lineno+1), "", line.strip()])
    return res


def grep(pattern, dirpath):
    r = re.compile(pattern, flags=re.IGNORECASE)
    res = []
    for parent, dirs, files in os.walk(dirpath):
        for f in files:
            filepath = os.path.join(parent, f)
            if os.path.isfile(filepath) and filepath.endswith(".rst"):
                with open(filepath) as f:
                    for (lineno, line) in enumerate(f):
                        if r.search(line):
                            # remove startdir from filepath
                            filepath = os.path.normpath(filepath)
                            filepath = filepath.replace(startdir, "", 1)
                            if filepath[0] == "/":
                                filepath = filepath[1:]
                            res.append([str(lineno+1), filepath, line.strip()])
    return res


def run(cmd, stdin=None, cwd=None):
    # blocking!

    proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = proc.communicate(input=stdin, timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        (out, err) = proc.communicate()
    ret = out.decode().strip()
    if not ret:
        ret = err.decode().strip()
    return proc.returncode, ret


def git_get_rev(filename):

    (ret, cnt) = run(["git", "rev-list", "--count", "HEAD"])
    (ret, hsh) = run(["git", "rev-parse", "--short", "HEAD"])
    rev = "r" + cnt + "." + hsh
    (ret, drt) = run(["git", "status", "--porcelain", filename])
    # ?? untracked
    # 
    log.debug("ret: " + str(ret))
    log.debug("drt: " + drt)
    if drt:
        if "M" in drt.split(" ")[0]:
            rev += " dirty"
        else:
            rev = "untracked"
    log.debug(rev)

    return rev


def handle_spaces(rstin):
    rstout = ""
    reg = re.compile("`.*<.* .*>`_")
    for line in rstin.splitlines():
        mat = reg.search(line)
        if mat:
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
                    c = rechar
                fuck += c
            line = fuck
        rstout += line + "\n"
    return rstout


if __name__ == "__main__":

    global rechar
    rechar = u"\u02FD"

    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action='store_true')
    parser.add_argument("path", nargs=1)
    args = parser.parse_args()

    global log
    log = logging.getLogger()
    log.propagate = False

    hdlr = logging.StreamHandler()
    log.addHandler(hdlr)

    log.setLevel(logging.ERROR)

    if args.verbose:
        log.setLevel(logging.DEBUG)

    default_config = """
    [labnote]
    right_side_editor = True
    source_view_scheme = default
    stylesheet = 
    """
    config = configparser.SafeConfigParser()
    config.read_string(default_config)

    configpath_ = os.getenv("XDG_CONFIG_HOME")
    if not configpath_:
        configpath_ = os.path.expanduser("~/.config")

    configpath = configpath_ + "/labnote/config.ini"
    try:
        configfile = open(configpath, "r+")
        config.read_file(configfile)
        configfile.close()
    except FileNotFoundError:
        configdir = os.path.dirname(configpath)
        if not os.path.exists(configdir):
            os.makedirs(configdir)
        configfile = open(configpath, "w")
        config.write(configfile)
        configfile.close()

    right_side_editor = config.getboolean("labnote", "right_side_editor")
    source_view_scheme = config.get("labnote", "source_view_scheme")
    stylesheet = config.get("labnote", "stylesheet")
    # TODO ugly
    if stylesheet != "":
        stylesheet = configpath_ + "/labnote/" + stylesheet


    start = args.path[0]
    log.debug("startpath " + start)

    mimetypes.init()

    start = os.path.abspath(start)
    global startdir
    startdir = os.path.dirname(start)
    os.chdir(startdir)
    startfile = os.path.basename(start)

    # check for git
    (ret, out) = run(["git", "status"])

    if ret == 0:
        git = True
    else:
        git = False


    global loop
    loop = GObject.MainLoop(None)

    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    try:
        window = mainwindow(source_view_scheme, stylesheet, right_side_editor, git)

        window.history_home = startfile
        window.webview.load_uri("file://" + startfile)

        loop.run()
    except KeyboardInterrupt:
        window.shutdown()

