#!/usr/bin/env python3

# Copyright 2016-2018 Thomas Krug
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
import datetime
import io
import logging
import mimetypes
import os
import random
import re
import shutil
import signal
import string
import subprocess
import sys
import tempfile
import threading
import time
import urllib
import urllib.request
import urllib.parse

# Debian Jessie
#   python3-gi
#   gir1.2-webkit2-3.0
#   gir1.2-gtksource-3.0
#   python3-docutils

# Arch
# ttf-dejavu

# python-gobject
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GObject, Gtk, Pango, Gdk, GLib, Gio

# webkit2gtk
try:
    gi.require_version('WebKit2', '4.0')
except ValueError:
    gi.require_version('WebKit2', '3.0')
from gi.repository import WebKit2

# gtksourceview3
gi.require_version('GtkSource', '3.0')
#gi.require_version('GtkSource', '4')
from gi.repository import GtkSource

# python-docutils
#   python-pygments (code highlighting)
#   ttf-droid (better formula view)
import docutils
import docutils.core

# TODO
# - git
#   - add file if created by paste
#   - on ext file open, check if added (only in tree)
#   - "commit -a" before push on exit?
#     (currently only on file change)
#     - only commit on own change?
#   - state in statusbar?
#
#   libgit2 via pygit2
#   -> write small wrapper for git binary
#
# - better scrolling to current edit
# - better focus handling
#   - startup
#   - after closing searchbar
# - quick insert utf8 symbols, arrows etc.
# - fixed size allocation?
# - reset buffer history on save?
# - lock loading (ie file change on search)
#
# rST
# - latex export emits \href instead of \includegraphics on image, when secifying :target:
#   - quick fix: remove target before exporting to latex?
# - rst does not handle spaces in references
#

class mainwindow():

    def __init__(self, config, git):

        self.config = config
        self.git = git

        self.load_state = 0
        self.lock_line = 0
        # this is used to lock the rendering for buffer updates
        # gtk thread triggers an update, which is executed by
        # callback in webkit thread
        self.update_lock = False
        self.update_deferred = False

        self.deferred_line = 0

        self.current_file = ""

        self.history_home = ""
        self.history_stack = []
        self.history_ignore = False

        self.extern = ["http", "https", "ftp", "ftps", "mailto"]


        self.window = Gtk.Window()
        self.window.connect("delete-event", self.on_delete_event)
        self.window.connect("key-press-event", self.window_on_key_press)
        self.window.set_title("LabNote")
        self.window.set_role("labnote")

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
        self.window.set_size_request(1400, 800)
        self.window.set_position(Gtk.WindowPosition.CENTER)


        ##
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.window.add(vbox)


        tb_back = Gtk.Button()
        icon = Gio.ThemedIcon.new_with_default_fallbacks("go-previous-symbolic")
        img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.SMALL_TOOLBAR)
        tb_back.add(img)
        tb_back.connect("clicked", self.go_back)


        toolbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        self.entry = Gtk.Entry()
        self.entry.connect("activate", self.on_entry_act)

        toolbox.pack_start(tb_back, False, False, 0)
        toolbox.pack_start(self.entry, True, True, 0)

        vbox.pack_start(toolbox, False, False, 0)


        self.scrolledwindow = Gtk.ScrolledWindow()
        self.scrolledwindow.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        ## SourceView
        self.textview = GtkSource.View()
        # TODO set from theme (Gtk.Style) or config
        #self.textview.override_font(Pango.FontDescription("DejaVu Sans Mono 10"))
        self.textview.set_monospace(True)
        self.textview.set_tab_width(2)
        self.textview.set_insert_spaces_instead_of_tabs(True)
        self.textview.set_show_line_numbers(True)
        self.textview.set_right_margin_position(80)
        self.textview.set_show_right_margin(True)
        self.textview.set_highlight_current_line(True)
        #self.textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.textview.set_wrap_mode(Gtk.WrapMode.NONE)
        self.textview.set_auto_indent(True)
        self.textview.set_smart_home_end(True)

        # show trailing whitespace (gtk >= 3.24)
        spacedrawer = self.textview.get_space_drawer()
        # seems to turn all on
        spacedrawer.set_enable_matrix(True)
        # all off
        spacedrawer.set_types_for_locations(GtkSource.SpaceLocationFlags.ALL,
                                            GtkSource.SpaceTypeFlags.NONE)
        # display all trailing whitespaces
        spacedrawer.set_types_for_locations(GtkSource.SpaceLocationFlags.TRAILING,
                                            GtkSource.SpaceTypeFlags.SPACE)

        self.tvbuffer = self.textview.get_buffer()
        self.tvbuffer.props.language = GtkSource.LanguageManager.get_default().get_language('rst')
        ssm = GtkSource.StyleSchemeManager.get_default()
        scheme = ssm.get_scheme(self.config["sourceview_scheme"])
        self.tvbuffer.props.style_scheme = scheme

        self.textview.connect("size-allocate", self.textview_on_size_allocate)
        self.tvbuffer.connect("changed", self.buffer_changed)

        um = self.tvbuffer.get_undo_manager()
        um.connect("can-undo-changed", self.buffer_undo)

        self.scrolledwindow.add(self.textview)


        ## WebKit
        self.webview = WebKit2.WebView()

        settings = self.webview.get_settings()
        settings.set_enable_javascript(True)

        settings.set_allow_file_access_from_file_urls(True)
        settings.set_allow_universal_access_from_file_urls(True)
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

        # TODO set from theme (Gtk.Style) or config
        #settings.set_default_font_family("DejaVu")
        #settings.set_serif_font_family("DejaVu Serif")
        #settings.set_sans_serif_font_family("DejaVu Sans")
        #settings.set_monospace_font_family("DejaVu Sans Mono")
        settings.set_default_font_size(14)
        settings.set_minimum_font_size(12)


        context = self.webview.get_context()
        context.register_uri_scheme("file", self.uri_scheme_file)
        for scheme in self.extern:
            context.register_uri_scheme(scheme, self.uri_scheme_deny)
        context.set_cache_model(WebKit2.CacheModel.DOCUMENT_VIEWER)
        context.clear_cache()

        self.webview.connect("decide-policy", self.load_policy)
        self.webview.connect("context-menu", self.disable_context_menu)
        self.webview.connect("load-changed", self.load_changed)
        # debug
        self.webview.connect("load-failed", self.load_failed)


        ##
        self.search_results = Gtk.ListStore(str, str, str)
        self.treeview = Gtk.TreeView(model=self.search_results)
        self.treeview.set_headers_visible(False)

        columns = ["filepath", "line", "lineno"]
        for (i, column) in enumerate(columns):
            cell = Gtk.CellRendererText()
            col = Gtk.TreeViewColumn(column, cell, text=i)
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
        hbox = Gtk.Box(orientation=self.config["layout"])
        if self.config["editor_first"]:
            # expand, fill, padding
            hbox.pack_start(self.scrolledwindow, True, True, 1)
            hbox.pack_start(self.webview, True, True, 1)
            hbox.pack_start(self.search_results_sw, True, True, 0)
        else:
            hbox.pack_start(self.search_results_sw, True, True, 0)
            hbox.pack_start(self.webview, True, True, 1)
            hbox.pack_start(self.scrolledwindow, True, True, 1)
        vbox.pack_start(hbox, True, True, 0)

        # search
        self.search = Gtk.SearchEntry()
        self.search.connect("activate", self.on_search)
        self.search.connect("key-press-event", self.on_search_key)

        self.searchr = Gtk.Revealer()
        self.searchr.add(self.search)

        vbox.pack_start(self.searchr, False, False, 0)

        self.info_bar = InfoBar(vbox)

        statusbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        vbox.pack_start(statusbar, False, False, 0)

        # TODO rename to msg and add helper functions (ie clearing after 5s)
        self.state = Gtk.Label()
        self.state_file = Gtk.Label()
        self.state_file.set_justify(Gtk.Justification.RIGHT)
        space = Gtk.Label()
        statusbar.pack_start(self.state, False, False, 3)
        statusbar.pack_start(space, True, True, 0)
        statusbar.pack_start(self.state_file, False, False, 6)

        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.primary_selection = Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY)

        self.textview.connect("key-press-event", self.twv_on_key_press)
        self.webview.connect("key-press-event", self.twv_on_key_press)
        self.textview.connect("button-press-event", self.twv_on_button_press)
        self.webview.connect("button-press-event", self.twv_on_button_press)

        vbox.show_all()
        self.window.show()
        self.search_results_sw.hide()
        self.textview.grab_focus()


    def textview_on_size_allocate(self, widget, allocation):

        if self.lock_line:
            it = self.tvbuffer.get_iter_at_line(self.lock_line)
            self.textview.scroll_to_iter(it, 0, True, 0.0, 0.0)

    def load_saved_request(self, request):
        self.tvbuffer.set_modified(False)
        self.webview.load_uri(request)


    def window_on_key_press(self, widget, event):

        # Ctrl
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            if event.keyval == ord("s"):
                log.debug("saving " + self.current_file)

                self.state_file.set_label("saving")

                #
                if self.git:
                    gitadd = bool(os.path.exists(self.current_file))

                filedir = os.path.dirname(self.current_file)
                if filedir:
                    if not os.path.exists(filedir):
                        os.makedirs(filedir)

                if save_file(self.current_file, self.tvbuffer.props.text):
                    self.tvbuffer.set_modified(False)
                    self.state_file.set_label("saved")
                else:
                    self.state_file.set_label("saving failed")
                    return True

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

            if event.keyval == ord("y"):
                # gedit maps redo to Ctrl-Shift-Z
                if self.tvbuffer.get_undo_manager().can_redo():
                    self.tvbuffer.get_undo_manager().redo()

            # Ctrl Shift
            if event.keyval == ord("F"):
                self.search_mode = "global"
                self.search.set_placeholder_text("search over files")
                self.searchr.set_reveal_child(True)
                self.search.grab_focus()

            if event.keyval == ord("E"):
                log.debug("start export")
                self.state.set_label("exporting")

                rst = self.tvbuffer.props.text

                meta = {}
                meta["title"] = self.current_file.replace("_", "\_")  # pylint: disable=anomalous-backslash-in-string
                if self.git:
                    meta["rev"] = git_get_rev(self.current_file)
                else:
                    meta["rev"] = ""
                # TODO use git date, use current date only if no git or dirty
                # git log -1 --date=iso-strict --format=%cd <file>
                meta["dt"] = datetime.datetime.now().strftime("%Y-%m-%d")

                tex = rst2tex(rst, meta, self.config)
                if not tex:
                    self.state.set_label("export failed (rst to tex)")
                    return True

                export = threading.Thread(target=tex2pdf,
                                          args=[tex, os.path.dirname(self.current_file),
                                                "/tmp/labnote.pdf", self.export_done])
                export.daemon = True
                export.start()
                return True

        # Alt
        if event.state & Gdk.ModifierType.MOD1_MASK:

            if event.keyval == Gdk.KEY_Left:
                log.debug("go back")
                self.go_back()
                return True

            if event.keyval == Gdk.KEY_Up:
                log.debug("go home")
                self.load_uri(self.history_home)
                return True

            if event.keyval == Gdk.KEY_Down:
                scroll = self.webview.get_title()
                try:
                    scroll = float(scroll)
                except ValueError:
                    scroll = 0
                adj = self.scrolledwindow.get_vadjustment()
                scale = adj.props.upper - adj.props.lower
                adj.set_value(scroll * scale)
                self.textview.set_vadjustment(adj)
                return True

        return False


    def export_done(self, err):

        if not err:
            log.debug("export done")
            self.state.set_label("export done")
            self.open_uri("/tmp/labnote.pdf")
        else:
            log.debug("export failed")
            self.state.set_label("export failed (tex to pdf)")

    def absorb_file(self, src):
        # copy to current dir
        current_dir = os.path.dirname(os.path.join(startdir, self.current_file))
        #if current_dir:
        #    if not os.path.exists(current_dir):
        #        os.makedirs(current_dir)
        try:
            shutil.copy(src, current_dir + "/")
        except shutil.SameFileError:
            self.tvbuffer.insert_at_cursor(src + "\n")
            return
        except PermissionError:
            # TODO notify about errors
            return
        except FileNotFoundError:
            # TODO notify about errors
            return

        fn = os.path.basename(src)
        # TODO add to git

        # insert reference
        (typ, enc) = mimetypes.guess_type(fn)
        if typ and typ.startswith("image"):
            self.tvbuffer.insert_at_cursor(".. image:: " + fn + "\n   :target: " + fn + "\n")
        else:
            self.tvbuffer.insert_at_cursor("`<" + fn + ">`__\n")

    def set_state(self, state):
        GLib.idle_add(self.set_state_cb, state)

    def set_state_cb(self, state):
        self.state.set_label(state)

    def twv_on_key_press(self, widget, event):

        if event.state & Gdk.ModifierType.CONTROL_MASK:

            if event.keyval == ord("v"):
                # handling of clipboard pasting

                # move to drag & drop?
                if self.clipboard.wait_is_uris_available():
                    uris = self.clipboard.wait_for_uris()
                    for uri in uris:
                        if uri.startswith("file://"):
                            fp = uri[7:]
                            self.info_bar.ask("Copy file to notes?", fp,
                                              self.absorb_file, None)
                            # will add only first uri starting with file
                            return True

                if self.clipboard.wait_is_image_available():
                    # only interact if its an image
                    img = self.clipboard.wait_for_image()
                    if not img:
                        return False

                    current_dir = os.path.dirname(self.current_file)
                    if current_dir:
                        if not os.path.exists(current_dir):
                            os.makedirs(current_dir)

                    while True:
                        imgname = "".join(random.choice(string.ascii_lowercase + string.digits) for i in range(12))
                        imgname += ".png"
                        imgpath = os.path.join(current_dir, imgname)
                        try:
                            imgfd = os.open(imgpath, os.O_CREAT | os.O_EXCL)
                        except FileExistsError:
                            continue
                        os.close(imgfd)
                        break

                    img.savev(imgpath, "png", [None], [None])
                    # TODO add to git

                    sel = self.tvbuffer.get_selection_bounds()
                    self.lock()
                    if sel:
                        self.tvbuffer.delete(sel[0], sel[1])
                    self.tvbuffer.insert_at_cursor(".. image:: " + imgname + "\n   :target: " + imgname + "\n")
                    self.unlock()

                    return True

                if self.clipboard.wait_is_text_available():
                    txt = self.clipboard.wait_for_text()
                    if not txt:
                        return True
                    sel = self.tvbuffer.get_selection_bounds()
                    self.lock()
                    if sel:
                        self.tvbuffer.delete(sel[0], sel[1])
                    self.tvbuffer.insert_at_cursor(txt)
                    self.unlock()
                    return True


            if event.keyval == ord("V"):

                clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
                text = clipboard.wait_for_text()

                if not text:
                    return True

                text_ = ""
                for line in text.splitlines():
                    text_ += "  " + line + "\n"

                sel = self.tvbuffer.get_selection_bounds()
                self.lock()
                if sel:
                    self.tvbuffer.delete(sel[0], sel[1])
                self.tvbuffer.insert_at_cursor(text_)
                self.unlock()

                return True

    def twv_on_button_press(self, widget, event):
        (ok, button) = event.get_button()

        if button == 8:
            self.go_back()
            return True
        if button == 9:
            #self.go_forward()
            return True

        # handle pasting of primary selection
        if button == Gdk.BUTTON_MIDDLE:
            if self.tvbuffer.get_selection_bounds():
                # if the selection comes from us
                # we paste it at pointer location
                return False

            # if the selection does not come from us
            # we paste put it at cursor location
            if self.primary_selection.wait_is_text_available():
                txt = self.primary_selection.wait_for_text()
                if txt:
                    self.tvbuffer.insert_at_cursor(txt)
                    return True

        return False


    def unlock(self):
        self.update_lock = False
        if self.update_deferred:
            self.update_deferred = False
            self.update_textview()

    def lock(self):
        if self.update_lock:
            self.update_deferred = True
            return False

        self.update_lock = True
        return True


    def load_uri(self, uri):
        self.webview.load_uri("file://labnote.int.abs/" + uri)


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
            log.debug("load finished")
            if log.isEnabledFor(logging.INFO):
                self.time_stop = time.clock_gettime(time.CLOCK_MONOTONIC)
                delta = self.time_stop - self.time_start
                log.info(str(delta))
            log.debug("----------")
            self.unlock()

            fred = threading.Thread(target=self.deferred)
            fred.daemon = True
            fred.start()


    def deferred(self):

        if self.deferred_line:
            log.debug("deferred jump")
            self.lock_line = self.deferred_line
            # GLib.idle_add not needed
            # request is "synchronized" via WebKit process
            self.update_textview()
            self.deferred_line = 0


    def disable_context_menu(self, view, menu, event, hittestresult):
        return True


    def load_policy(self, webview, decision, decision_type):
        if decision_type == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            log.debug("navigation policy for:")
            nav = decision.get_navigation_action()
            req = nav.get_request()
        if decision_type == WebKit2.PolicyDecisionType.RESPONSE:
            log.debug("response policy for:")
            req = decision.get_request()
        uri = req.get_uri()
        log.debug(uri)

        url = urllib.parse.urlparse(uri)

        if not url.scheme == "file":
            decision.ignore()

            if url.scheme in self.extern:
                self.open_uri(uri)

        return True


    def uri_scheme_deny(self, request):
        # .. image:: http://example.org/foo.jpg
        #
        # GLib-GObject-WARNING **: invalid cast from 'WebKitSoupRequestGeneric'
        #   to 'SoupRequestHTTP'
        # libsoup-CRITICAL **: soup_request_http_get_message:
        #   assertion 'SOUP_IS_REQUEST_HTTP (http)' failed
        #
        # "Custom URI schemes are for new schemes, not for overriding existing ones."

        # this is never executed
        log.debug("uri scheme denied " + request.get_uri())
        err = GLib.Error("load cancelled: extern")
        request.finish_error(err)


    def dtree_prep(self, dtree):
        ## path to uri

        for elem in dtree.traverse(siblings=True):
            if elem.tagname == "reference" or elem.tagname == "image":
                try:
                    if elem.tagname == "reference":
                        refuri = elem["refuri"]
                    if elem.tagname == "image":
                        refuri = elem["uri"]
                except KeyError:
                    continue

                refuri = ref2uri(refuri, os.path.dirname(self.current_file))
                if not refuri:
                    continue

                if elem.tagname == "reference":
                    elem["refuri"] = refuri
                if elem.tagname == "image":
                    elem["uri"] = refuri

        return dtree


    def uri_scheme_file(self, request):

        if log.isEnabledFor(logging.INFO):
            self.time_start = time.clock_gettime(time.CLOCK_MONOTONIC)

        uri = request.get_uri()
        log.debug("----------")
        log.debug("loading")
        log.debug("URI " + uri)
        log.debug("state " + str(self.load_state))

        # handle non ascii
        uri = urllib.request.unquote(uri)
        # handle spaces in links
        uri = uri.replace(rechar, " ")

        uri, ext = uri2path(uri, os.path.dirname(self.current_file), startdir)
        log.debug("URI " + uri)

        if self.load_state == 0:

            if uri.endswith(".rst") and not ext:

                if self.tvbuffer.get_modified():
                    log.debug("cancel due to modified")
                    err = GLib.Error("load cancelled: open file modified")
                    request.finish_error(err)

                    self.info_bar.ask("No write since last change. Proceed?", request.get_uri(),
                                      self.load_saved_request, None)
                    return

                self.load_rst(uri, request)

                self.state_file.set_label("")
                self.state.set_label("")
                return

            self.open_uri(uri)
            err = GLib.Error("load cancelled: file opened externally")
            request.finish_error(err)
            return

        if self.load_state == 1:
            (typ, enc) = mimetypes.guess_type(uri)
            log.debug(typ)
            if typ and typ.startswith("image"):
                self.load_img(uri, request)
            return


    def open_uri(self, uri):
        log.debug("opening external: " + uri)
        if log.isEnabledFor(logging.DEBUG):
            ret = subprocess.call(["/usr/bin/xdg-open", uri])
        else:
            ret = subprocess.call(["/usr/bin/xdg-open", uri],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if ret != 0:
            log.warning("could not be opened")


    def load_img(self, uri, request):
        log.debug("load image " + uri)
        try:
            stream = Gio.file_new_for_path(uri).read()
            request.finish(stream, -1, None)
        except GLib.Error:  # pylint: disable=catching-non-exception
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

        self.lock_line = 0
        html = self.render(txt)

        html = html.encode("latin-1", errors="xmlcharrefreplace")

        stream = Gio.MemoryInputStream.new_from_data(html)
        request.finish(stream, -1, None)


    def buffer_changed(self, textbuf):

        if not self.lock():
            return

        self.state_file.set_label("modified")

        self.update_textview()

    def update_textview(self):

        if log.isEnabledFor(logging.INFO):
            self.time_start = time.clock_gettime(time.CLOCK_MONOTONIC)

        if self.deferred_line:
            # set cursor
            it = self.tvbuffer.get_iter_at_line(self.deferred_line)
            self.tvbuffer.place_cursor(it)

        rst = self.tvbuffer.props.text

        html = self.render(rst, lock=True)

        base = "file://labnote.int.abs/" + self.current_file
        log.debug("base " + base)
        self.webview.load_html(html, base)


    def buffer_undo(self, manager):

        if not self.tvbuffer.get_modified():
            self.state_file.set_label("")


    def go_back(self, widget=None):
        if self.history_stack:
            self.history_ignore = True
            self.load_uri(self.history_stack[-1])
            del self.history_stack[-1]


    # load file (location bar)
    def on_entry_act(self, entry):
        self.load_uri(entry.get_text())


    # starting search
    def on_search(self, entry):
        pattern = entry.get_text()
        if not pattern:
            return

        self.search_results.clear()

        if self.search_mode == "global":
            res = grep(pattern, startdir)

            for r in res:
                self.search_results.append(r)

        if self.search_mode == "local":
            res = search(pattern, self.current_file)

            for r in res:
                self.search_results.append(r)

            # jump to first result
            if res:
                res_line = int(res[0][0]) - 1
                it = self.tvbuffer.get_iter_at_line(res_line)
                self.tvbuffer.place_cursor(it)
                self.textview.scroll_to_iter(it, 0, True, 0.0, 0.0)
                self.lock_line = res_line
                self.update_textview()

        self.webview.hide()
        self.search_results_sw.show()


    # search result activated
    def on_search_result(self, treeview, it, path):

        selection = treeview.get_selection()
        (model, pathlist) = selection.get_selected_rows()
        it = model.get_iter(pathlist[0])
        res_file = model.get_value(it, 1)
        res_line = int(model.get_value(it, 0)) - 1

        if self.search_mode == "global":
            self.deferred_line = res_line
            self.load_uri(res_file)

        if self.search_mode == "local":
            it_ = self.tvbuffer.get_iter_at_line(res_line)
            self.tvbuffer.place_cursor(it_)
            self.textview.scroll_to_iter(it_, 0, True, 0.0, 0.0)

            self.lock_line = res_line
            self.update_textview()


    def on_search_key(self, widget, event):

        if event.keyval == Gdk.KEY_Escape:
            self.lock_line = 0
            self.searchr.set_reveal_child(False)
            self.search_results_sw.hide()
            self.webview.show()


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

        # docutils: imho a bug
        rst = handle_spaces(rst)

        args = {
            "_disable_config": True,
            "embed_stylesheet": True,
            "output_encoding": "unicode"
        }

        stylepath = self.config["webview_style"]
        if stylepath:
            args["stylesheet_path"] = ""
            args["stylesheet"] = stylepath
            mathstyle = self.config["math_style"]
            if mathstyle:
                args["math_output"] = "HTML " + os.path.join(os.path.dirname(stylepath), mathstyle)


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

        # docutils: should really use logging
        with devnull():
            try:
                pargs = {"_disable_config": True, "doctitle_xform": False}
                dtree = docutils.core.publish_doctree(rst, settings_overrides=pargs)
            except docutils.utils.SystemMessage as e:
                return "<body>Error<br>" + str(e) + "</body>"

        dtree = self.dtree_prep(dtree)

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
            if log.isEnabledFor(logging.DEBUG):
                pretty = docutils.core.publish_from_doctree(dtree, writer_name="pseudoxml")

                with open("/tmp/labnote.dtree", "w") as f:
                    f.write(pretty.decode())

        with devnull():
            try:
                html = docutils.core.publish_from_doctree(dtree, writer_name="html4css1",
                            settings_overrides=args)

            except docutils.utils.SystemMessage as e:
                html = "<body>Error<br>" + str(e) + "</body>"
            except AttributeError as e:
                # docutils: parser should support optionally omitting broken nodes
                html = "<body>Error<br>" + str(e) + "</body>"

        script = "<head>\n<script>"
        body = '<body onscroll="update()"'

        script += r"""
        function update()
        {
            //var max = document.body.scrollHeight - window.innerHeight + 30;
            var max = document.body.scrollHeight - window.innerHeight;
            document.title = window.pageYOffset / max;
        }
        """

        if lock or self.lock_line:
            body += 'onload="scroll()"'

            script += r"""
            function scroll() {
              document.getElementById('btj0m1ve').scrollIntoView();
            }
            """

        body += '>'
        html = re.sub(r'<body>', body, html, re.M)

        script += "\n</script>"
        html = re.sub(r'<head>', script, html, re.M)

        # debug output
        if log.isEnabledFor(logging.DEBUG):
            with open("/tmp/labnote.html", "w") as f:
                f.write(html)

        return html


def ref2uri(refuri, curdir):
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


def rst2tex(rst, meta, conf):

    preamble = r"\usepackage{fancyhdr}"

    preamble_path = conf["latex_preamble"]
    if preamble_path:
        with open(preamble_path, "r") as preamble_file:
            preamble = preamble_file.read()

    preamble += "\\fancyhead[L]{" + meta["title"] + "}\n"
    preamble += "\\fancyfoot[L]{" + meta["rev"]   + "}\n"
    preamble += "\\fancyfoot[R]{" + meta["dt"] + "}\n"

    args = {"latex_preamble": preamble,
            "doctitle_xform": False}

    with devnull():
        try:
            tex = docutils.core.publish_string(rst, writer_name='latex',
                                               settings_overrides=args)
        except NotImplementedError:
            log.error("could not convert to tex")
            return None

    return tex.decode()

def tex2pdf(tex, srcdir, pdfpath, cb):
    srcdir = os.path.abspath(srcdir)
    pdfpath = os.path.abspath(pdfpath)

    tmpdir = tempfile.mkdtemp(prefix="labnote-")

    copytree(srcdir, tmpdir)

    with open(os.path.join(tmpdir, "labnote.tex"), "w") as f:
        f.write(tex)

    err = True
    for i in range(0, 4):
        (ret, out) = run(["pdflatex", "-halt-on-error", "labnote.tex"], cwd=tmpdir)
        if log.isEnabledFor(logging.DEBUG):
            log.debug(out)
        if ret != 0:
            log.error(out)
            break
        if "Rerun" in out or "undefined references" in out:
            continue
        else:
            shutil.move(os.path.join(tmpdir, "labnote.pdf"), pdfpath)
            err = False
            break

    if not log.isEnabledFor(logging.DEBUG):
        shutil.rmtree(tmpdir)

    GLib.idle_add(cb, err)


def copytree(src, dst):
    # behaves like "cp src/* dst/"
    for f in os.listdir(src):
        s = os.path.join(src, f)
        d = os.path.join(dst, f)
        if os.path.isdir(s):
            shutil.copytree(s, d, copy_function=shutil.copy)
        else:
            shutil.copy(s, d)


def save_file(fp, txt):

    # write-replace (unix style)
    fn = os.path.basename(fp)
    dn = os.path.dirname(fp)

    tfn = "." + fn + ".swp"
    tfp = os.path.join(dn, tfn)

    try:
        tfd = os.open(tfp, os.O_WRONLY | os.O_CREAT| os.O_EXCL, 0o600)
    except FileExistsError:
        return False

    with os.fdopen(tfd, "w") as tf:
        tf.write(txt)

    try:
        os.rename(tfp, fp)
    except OSError:
        return False

    return True


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


class InfoBar():

    def __init__(self, parent):
        self.rev = Gtk.Revealer()

        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.rev.add(self.box)

        self.label = Gtk.Label()
        self.box.pack_start(self.label, False, False, 2)

        self.button_yes = Gtk.Button()
        self.button_no = Gtk.Button()

        self.button_yes.set_label("  OK  ")
        self.button_no.set_label("Cancel")

        self.button_yes.connect("clicked", self.cb_ok)
        self.button_no.connect("clicked", self.cb_nok)

        self.box.pack_end(self.button_yes, False, False, 1)
        self.box.pack_end(self.button_no, False, False, 1)

        parent.pack_start(self.rev, False, False, 2)

        self.done()

    # default no
    def ask(self, question, userdata, cb_yes, cb_no):
        self.label.set_text(question)

        self.userdata = userdata
        self.cb_yes = cb_yes
        self.cb_no = cb_no

        self.rev.set_reveal_child(True)
        self.button_no.grab_focus()

    def done(self):
        self.rev.set_reveal_child(False)
        self.userdata = None
        self.cb_yes = None
        self.cb_no = None
        self.label.set_text("")

    def cb_ok(self, button):
        if self.cb_yes:
            self.cb_yes(self.userdata)
        self.done()

    def cb_nok(self, button):
        if self.cb_no:
            self.cb_no(self.userdata)
        self.done()


class devnull():
    def __init__(self):
        self.devnull = io.StringIO()

    def __enter__(self):
        sys.stdout = self.devnull
        sys.stderr = self.devnull

    def __exit__(self, type_, value, traceback):
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__


class ConfigParser():

    def __init__(self):

        self.default = """
        [labnote]
        default_path = ~/notes/index.rst
        sourceview_scheme = default
        webview_style = 
        math_style = 
        layout_vertical = False
        editor_first = False
        latex_preamble = 
        """
        self.parser = configparser.ConfigParser()
        self.config = {}

    def get_config(self):

        self.parser.read_string(self.default)

        config_home = os.getenv("XDG_CONFIG_HOME")
        if not config_home:
            config_home = os.path.expanduser("~/.config")

        config_dir = os.path.join(config_home, "labnote")
        config_path = os.path.join(config_dir, "config.ini")

        try:
            config_file = open(config_path, "r+")
            self.parser.read_file(config_file)
            config_file.close()
        except FileNotFoundError:
            if not os.path.exists(config_dir):
                os.makedirs(config_dir)
            config_file = open(config_path, "w")
            self.parser.write(config_file)
            config_file.close()

        default_path = self.parser.get("labnote", "default_path")
        if default_path:
            self.config["path"] = default_path

        layout_vertical = self.parser.getboolean("labnote", "layout_vertical")
        if layout_vertical:
            self.config["layout"] = Gtk.Orientation.VERTICAL
        else:
            self.config["layout"] = Gtk.Orientation.HORIZONTAL

        self.config["sourceview_scheme"] = self.parser.get("labnote", "sourceview_scheme")

        style = self.parser.get("labnote", "webview_style")
        if style:
            self.config["webview_style"] = os.path.join(config_dir, style)
        else:
            self.config["webview_style"] = None

        math = self.parser.get("labnote", "math_style")
        if math:
            self.config["math_style"] = math
        else:
            self.config["math_style"] = None

        self.config["editor_first"] = self.parser.getboolean("labnote", "editor_first")

        tex = self.parser.get("labnote", "latex_preamble")
        if tex:
            self.config["latex_preamble"] = os.path.join(config_dir, tex)
        else:
            self.config["latex_preamble"] = None

        return self.config


if __name__ == "__main__":

    global rechar
    rechar = u"\u02FD"

    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="count")
    parser.add_argument("path", nargs="?")
    args = parser.parse_args()

    global log
    log = logging.getLogger()
    log.propagate = False

    hdlr = logging.StreamHandler()
    log.addHandler(hdlr)

    log.setLevel(logging.ERROR)

    if args.verbose:
        if args.verbose == 1:
            log.setLevel(logging.INFO)
        if args.verbose >= 2:
            log.setLevel(logging.DEBUG)

    config_parser = ConfigParser()
    config = config_parser.get_config()


    if args.path:
        start = os.path.expanduser(args.path)
    else:
        start = os.path.expanduser(config["path"])
    log.debug("startpath " + start)

    # try to open default
    if os.path.isdir(start):
        start = os.path.join(start, "index.rst")

    mimetypes.init()

    # this adds cwd!
    start = os.path.abspath(start)
    global startdir
    startdir = os.path.dirname(start)
    log.debug("startdir " + startdir)
    os.chdir(startdir)
    startfile = os.path.basename(start)

    # check for git, but only if our startdir is a git root
    if os.path.isdir(startdir + "/.git"):
        log.debug("startdir is a git root")
        git = True
    else:
        log.debug("startdir is NO git root")
        git = False

    global loop
    loop = GLib.MainLoop(None)

    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    try:
        window = mainwindow(config, git)

        window.history_home = startfile
        window.load_uri(startfile)

        loop.run()
    except KeyboardInterrupt:
        window.shutdown()

