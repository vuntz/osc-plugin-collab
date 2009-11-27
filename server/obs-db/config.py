# vim: set ts=4 sw=4 et: coding=UTF-8

#
# Copyright (c) 2009, Novell, Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#  * Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#  * Neither the name of the <ORGANIZATION> nor the names of its contributors
#    may be used to endorse or promote products derived from this software
#    without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
#
# (Licensed under the simplified BSD license)
#
# Authors: Vincent Untz <vuntz@opensuse.org>
#

import os
import sys

import ConfigParser
import cStringIO as StringIO

from osc import conf as oscconf
from osc import oscerr

""" Example:
[General]
threads = 5

[Defaults]
branch = latest

[Project openSUSE:Factory]

[Project GNOME:STABLE:2.26]
branch = gnome-2-26
ignore-fallback = true
"""

#######################################################################


class ConfigException(Exception):
    pass


#######################################################################


class EasyConfigParser(ConfigParser.SafeConfigParser):

    def safe_get(self, section, option, default):
        try:
            return self.get(section, option)
        except:
            return default


    def safe_getint(self, section, option, default):
        try:
            return self.getint(section, option)
        except:
            return default


    def safe_getboolean(self, section, option, default):
        try:
            return self.getboolean(section, option)
        except:
            return default


#######################################################################


class ConfigProject:

    default_checkout_devel_projects = False
    default_parent = ''
    default_branch = ''
    default_ignore_fallback = False
    default_force_project_parent = False
    default_lenient_delta = False


    @classmethod
    def set_defaults(cls, cp, section):
        """ Set new default settings for projects. """
        cls.default_checkout_devel_projects = cp.safe_getboolean(section, 'checkout-devel-projects', cls.default_checkout_devel_projects)
        cls.default_parent = cp.safe_get(section, 'parent', cls.default_parent)
        cls.default_branch = cp.safe_get(section, 'branch', cls.default_branch)
        cls.default_ignore_fallback = cp.safe_getboolean(section, 'ignore-fallback', cls.default_ignore_fallback)
        cls.default_force_project_parent = cp.safe_getboolean(section, 'force-project-parent', cls.default_force_project_parent)
        cls.default_lenient_delta = cp.safe_getboolean(section, 'lenient-delta', cls.default_lenient_delta)


    def __init__(self, cp, section, name):
        self.name = name

        self.checkout_devel_projects = cp.safe_getboolean(section, 'checkout-devel-projects', self.default_checkout_devel_projects)
        self.parent = cp.safe_get(section, 'parent', self.default_parent)
        self.branch = cp.safe_get(section, 'branch', self.default_branch)
        self.ignore_fallback = cp.safe_getboolean(section, 'ignore-fallback', self.default_ignore_fallback)
        self.force_project_parent = cp.safe_getboolean(section, 'force-project-parent', self.default_force_project_parent)
        self.lenient_delta = cp.safe_getboolean(section, 'lenient-delta', self.default_lenient_delta)


#######################################################################


class Config:

    def __init__(self, file = ''):
        """ Arguments:
            file -- configuration file to use

        """
        self.filename = file
        self.apiurl = None
        self.hermes_urls = []
        self._hermes_urls_helper = ''
        self.cache_dir = os.path.realpath('cache')
        self.threads = 10
        self.sockettimeout = 30
        self.threads_sockettimeout = 30

        self.debug = False
        self.mirror_only_new = False
        self.force_hermes = False
        self.force_db = False
        self.skip_hermes = False
        self.skip_mirror = False
        self.skip_db = False

        self.projects = {}

        self._parse()

        # Workaround to remove warning coming from osc.conf when we don't use
        # SSL checks
        buffer = StringIO.StringIO()
        oldstderr = sys.stderr
        sys.stderr = buffer

        try:
            oscconf.get_config(override_apiurl = self.apiurl)
        except oscerr.NoConfigfile, e:
            raise ConfigException(e.msg)

        # Workaround to remove warning coming from osc.conf when we don't use
        # SSL checks
        sys.stderr = oldstderr
        self._copy_stderr_without_ssl(buffer)
        buffer.close()

        # Make sure apiurl points to the right value
        self.apiurl = oscconf.config['apiurl']

        # M2Crypto and socket timeout are not friends. See
        # https://bugzilla.osafoundation.org/show_bug.cgi?id=2341
        if (oscconf.config['api_host_options'][self.apiurl].has_key('sslcertck') and
            oscconf.config['api_host_options'][self.apiurl]['sslcertck']):
            self.sockettimeout = 0

        # obviously has to be done after self.sockettimeout has been set to its
        # final value
        if self.threads_sockettimeout <= 0:
            self.threads_sockettimeout = self.sockettimeout


    def _copy_stderr_without_ssl(self, buffer):
        """ Copy the content of a string io to stderr, except for the SSL warning. """
        buffer.seek(0)
        ignore_empty = False
        while True:
            line = buffer.readline()
            if len(line) == 0:
                break
            if line == 'WARNING: SSL certificate checks disabled. Connection is insecure!\n':
                ignore_empty = True
                continue
            if line == '\n' and ignore_empty:
                ignore_empty = False
                continue
            ignore_empty = False
            print >>sys.stderr, line[:-1]

    def _parse(self):
        """ Parse the configuration file. """
        if not self.filename:
            return

        if not os.path.exists(self.filename):
            raise ConfigException('Configuration file %s does not exist.' % self.filename)

        cp = EasyConfigParser()
        cp.read(self.filename)

        self._parse_general(cp)
        self._parse_debug(cp)
        self._parse_default_project(cp)
        self._parse_projects(cp)


    def _parse_general(self, cp):
        """ Parses the section about general settings. """
        if not cp.has_section('General'):
            return

        self.apiurl = cp.safe_get('General', 'apiurl', self.apiurl)
        self._hermes_urls_helper = cp.safe_get('General', 'hermes-urls', self._hermes_urls_helper)
        self.cache_dir = os.path.realpath(cp.safe_get('General', 'cache-dir', self.cache_dir))
        self.threads = cp.safe_getint('General', 'threads', self.threads)
        self.sockettimeout = cp.safe_getint('General', 'sockettimeout', self.sockettimeout)
        self.threads_sockettimeout = cp.safe_getint('General', 'threads-sockettimeout', self.threads_sockettimeout)

        if self._hermes_urls_helper:
            self.hermes_urls = [ url.strip() for url in self._hermes_urls_helper.split(',') ]


    def _parse_debug(self, cp):
        """ Parses the section about debug settings. """
        if not cp.has_section('Debug'):
            return

        self.debug = cp.safe_getboolean('Debug', 'debug', self.debug)
        self.mirror_only_new = cp.safe_getboolean('Debug', 'mirror-only-new', self.mirror_only_new)
        self.force_hermes = cp.safe_getboolean('Debug', 'force-hermes', self.force_hermes)
        self.force_db = cp.safe_getboolean('Debug', 'force-db', self.force_db)
        self.skip_hermes = cp.safe_getboolean('Debug', 'skip-hermes', self.skip_hermes)
        self.skip_mirror = cp.safe_getboolean('Debug', 'skip-mirror', self.skip_mirror)
        self.skip_db = cp.safe_getboolean('Debug', 'skip-db', self.skip_db)


    def _parse_default_project(self, cp):
        """ Parses the section about default settings for projects. """
        if not cp.has_section('Defaults'):
            return

        ConfigProject.set_defaults(cp, 'Defaults')


    def _parse_projects(self, cp):
        """ Parses the project sections. """
        for section in cp.sections():
            if not section.startswith('Project '):
                continue

            name = section[len('Project '):]
            if self.projects.has_key(name):
                raise ConfigException('More than one section for project %s in %s.' % (name, self.filename))

            project = ConfigProject(cp, section, name)
            self.projects[name] = project
