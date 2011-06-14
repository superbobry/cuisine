# -*- coding: utf-8 -*-
"""
    cusisine
    ~~~~~~~~

    ``cuisine`` makes it easy to write automatic server installation and
    configuration recipies by wrapping common administrative tasks
    (installing packages, creating users and groups) in Python functions.

    ``cuisine`` is designed to work with Fabric and provide all you need
    for getting your new server up and running in minutes.

    Note, that right now, Cuisine only supports Debian-based Linux systems.

    .. seealso::

       `Deploying Django with Fabric
       <http://lethain.com/entry/2008/nov/04/deploying-django-with-fabric>`_

       `Notes on Python Fabric 0.9b1
       <http://www.saltycrane.com/blog/2009/10/notes-python-fabric-09b1>`_

       `EC2, fabric, and "err: stdin: is not a tty"
       <http://blog.markfeeney.com/2009/12/ec2-fabric-and-err-stdin-is-not-tty.html>`_

    :copyright: (c) 2011 by Sebastien Pierre, see AUTHORS for more details.
    :license: BSD, see LICENSE for more details.
"""

import bz2
import crypt
import os
import random
import re
import string
from functools import wraps

import fabric
import fabric.api
import fabric.context_managers


MODE      = "user"
RE_SPACES = re.compile("[\s\t]+")


def mode_user():
	"""Cuisine functions will be executed as the current user."""
	global MODE
	MODE = "user"


def mode_sudo():
	"""Cuisine functions will be executed with sudo."""
	global MODE
	MODE = "sudo"


def run(*args, **kwargs):
	"""A wrapper around :func:`~fabric.api.sudo` and
    :func:`~fabric.api.run`, which uses an appropriate command, based
    on the value of ``cuisine.MOD`` global.
    """
	if MODE == "sudo":
		return fabric.api.sudo(*args, **kwargs)
	else:
		return fabric.api.run(*args, **kwargs)

sudo = fabric.api.sudo


def multiargs(func):
    """Decorator changing the decorated function to accept multiple
    arguments. When called with a sequence type as first argument,
    applies the decorated function to each of the sequence items,
    otherwise executes it `normaly` (i.e. with the given arguments).

    >>> @multiargs
    ... def foo(arg):
    ...    print(arg)
    ...
    >>> foo("bar")
    bar
    >>> foo(["bar", "baz"])
    bar
    baz
    [None, None]
    """
    @wraps(func)
    def inner(*args, **kwargs):
        if args and isinstance(args[0], (list, tuple)):
            return map(lambda a: func(a, *args[1:], **kwargs), args[0])
        else:
            return func(*args, **kwargs)
    return inner


def local_read( location ):
	"""Reads a *local* file from the given location, expanding '~' and shell variables."""
	p = os.path.expandvars(os.path.expanduser(location))
	f = file(p, 'rb')
	t = f.read()
	f.close()
	return t

def dir_attribs(location, mode=None, owner=None, group=None, recursive=False):
	"""Updates the mode/owner/group for the given remote directory."""
	file.attrs(location, mode, owner, group, recursive)

def dir_exists( location ):
	"""Tells if there is a remote directory at the given location."""
	return run("test -d '%s' && echo OK ; true" % (location)).endswith("OK")

def dir_ensure( location, recursive=False, mode=None, owner=None, group=None ):
	"""Ensures that there is a remote directory at the given location, optionnaly
	updating its mode/owner/group.

	If we are not updating the owner/group then this can be done as a single
	ssh call, so use that method, otherwise set owner/group after creation."""
	if mode:
		mode_arg = "-m %s" % (mode)
	else:
		mode_arg = ""
	sudo("(test -d '%s' || mkdir %s %s '%s') && echo OK ; true" % (location, recursive and "-p" or "", mode_arg, location))
	if owner or group:
		dir_attribs(location, owner=owner, group=group)

def command_check( command ):
	"""Tests if the given command is available on the system."""
	return run("which '%s' >& /dev/null && echo OK ; true" % command).endswith("OK")

def package_update( package=None ):
	"""Updates the package database (when no argument) or update the package
	or list of packages given as argument."""
	if package == None:
		sudo("apt-get --yes update")
	else:
		if type(package) in (list,tuple): package = " ".join(package)
		sudo("apt-get --yes upgrade " + package)

def package_install( package, update=False ):
	"""Installs the given package/list of package, optionnaly updating the package
	database."""
	if update: sudo("apt-get --yes update")
	if type(package) in (list,tuple): package = " ".join(package)
	sudo("apt-get --yes install %s" % (package))

@multiargs
def package_ensure( package ):
	"""Tests if the given package is installed, and installes it in case it's not
	already there."""
	if run("dpkg-query -W -f='${Status}' %s ; true" % package).find("installed") == -1:
		package_install(package)

def command_ensure( command, package=None ):
	"""Ensures that the given command is present, if not installs the package with the given
	name, which is the same as the command by default."""
	if package is None: package = command
	if not command_check(command): package_install(package)
	assert command_check(command), "Command was not installed, check for errors: %s" % (command)

def user_create( name, passwd=None, home=None, uid=None, gid=None, shell=None, uid_min=None, uid_max=None):
	"""Creates the user with the given name, optionally giving a specific password/home/uid/gid/shell."""
	options = ["-m"]
	if passwd:
		method = 6
		saltchars = string.ascii_letters + string.digits + './'
		salt = ''.join([random.choice(saltchars) for x in range(8)])
		passwd_crypted = crypt.crypt(passwd, '$%s$%s' % (method, salt))
		options.append("-p '%s'" % (passwd_crypted))
	if home: options.append("-d '%s'" % (home))
	if uid:  options.append("-u '%s'" % (uid))
	if gid:  options.append("-g '%s'" % (gid))
	if shell: options.append("-s '%s'" % (shell))
	if uid_min:  options.append("-K UID_MIN='%s'" % (uid_min))
	if uid_max:  options.append("-K UID_MAX='%s'" % (uid_max))
	sudo("useradd %s '%s'" % (" ".join(options), name))

def user_check( name ):
	"""Checks if there is a user defined with the given name, returning its information
	as a '{"name":<str>,"uid":<str>,"gid":<str>,"home":<str>,"shell":<str>}' or 'None' if
	the user does not exists."""
	d = sudo("cat /etc/passwd | egrep '^%s:' ; true" % (name))
	s = sudo("cat /etc/shadow | egrep '^%s:' | awk -F':' '{print $2}'" % (name))
	results = {}
	if d:
		d = d.split(":")
		results = dict(name=d[0],uid=d[2],gid=d[3],home=d[5],shell=d[6])
	if s:
		results['passwd']=s
	if results:
		return results
	else:
		return None

def user_ensure( name, passwd=None, home=None, uid=None, gid=None, shell=None):
	"""Ensures that the given users exists, optionally updating their passwd/home/uid/gid/shell."""
	d = user_check(name)
	if not d:
		user_create(name, passwd, home, uid, gid, shell)
	else:
		options=[]
		if passwd != None and d.get('passwd') != None:
			method, salt = d.get('passwd').split('$')[1:3]
			passwd_crypted = crypt.crypt(passwd, '$%s$%s' % (method, salt))
			if passwd_crypted != d.get('passwd'):
				options.append("-p '%s'" % (passwd_crypted))
		if passwd != None and d.get('passwd') is None:
			# user doesn't have passwd
			method = 6
			saltchars = string.ascii_letters + string.digits + './'
			salt = ''.join([random.choice(saltchars) for x in range(8)])
			passwd_crypted = crypt.crypt(passwd, '$%s$%s' % (method, salt))
			options.append("-p '%s'" % (passwd_crypted))
		if home != None and d.get("home") != home:
			options.append("-d '%s'" % (home))
		if uid  != None and d.get("uid") != uid:
			options.append("-u '%s'" % (uid))
		if gid  != None and d.get("gid") != gid:
			options.append("-g '%s'" % (gid))
		if shell != None and d.get("shell") != shell:
			options.append("-s '%s'" % (shell))
		if options:
			sudo("usermod %s '%s'" % (" ".join(options), name))

def group_create( name, gid=None ):
	"""Creates a group with the given name, and optionally given gid."""
	options = []
	if gid:  options.append("-g '%s'" % (gid))
	sudo("groupadd %s '%s'" % (" ".join(options), name))

def group_check( name ):
	"""Checks if there is a group defined with the given name, returning its information
	as a '{"name":<str>,"gid":<str>,"members":<list[str]>}' or 'None' if the group
	does not exists."""
	group_data = run("cat /etc/group | egrep '^%s:' ; true" % (name))
	if group_data:
		name,_,gid,members = group_data.split(":",4)
		return dict(name=name,gid=gid,members=tuple(m.strip() for m in members.split(",")))
	else:
		return None

def group_ensure( name, gid=None ):
	"""Ensures that the group with the given name (and optional gid) exists."""
	d = group_check(name)
	if not d:
		group_create(name, gid)
	else:
		if gid != None and d.get("gid") != gid:
			sudo("groupmod -g %s '%s'" % (gid, name))

def group_user_check( group, user ):
	"""Checks if the given user is a member of the given group. It will return 'False'
	if the group does not exist."""
	d = group_check(group)
	if d is None:
		return False
	else:
		return user in d["members"]

@multiargs
def group_user_add( group, user ):
	"""Adds the given user/list of users to the given group/groups."""
	assert group_check(group), "Group does not exist: %s" % (group)
	if not group_user_check(group, user):
		lines = []
		for line in file_read("/etc/group").split("\n"):
			if line.startswith(group + ":"):
				if line.strip().endswith(":"):
					line = line + user
				else:
					line = line + "," + user
			lines.append(line)
		text = "\n".join(lines)
		file_write("/etc/group", text)

def group_user_ensure( group, user):
	"""Ensure that a given user is a member of a given group."""
	d = group_check(group)
	if user not in d["members"]:
		group_user_add(group, user)

def ssh_keygen( user, keytype="dsa" ):
	"""Generates a pair of ssh keys in the user's home .ssh directory."""
	d = user_check(user)
	assert d, "User does not exist: %s" % (user)
	home = d["home"]
	if not file_exists(home + "/.ssh/id_%s.pub" % keytype):
		dir_ensure(home + "/.ssh", mode="0700", owner=user, group=user)
		run("ssh-keygen -q -t %s -f '%s/.ssh/id_%s' -N ''" % (home, keytype, keytype))
		file_attribs(home + "/.ssh/id_%s" % keytype,     owner=user, group=user)
		file_attribs(home + "/.ssh/id_%s.pub" % keytype, owner=user, group=user)

def ssh_authorize( user, key ):
	"""Adds the given key to the '.ssh/authorized_keys' for the given user."""
	d    = user_check(user)
	keyf = d["home"] + "/.ssh/authorized_keys"
	if file_exists(keyf):
		if file_read(keyf).find(key) == -1:
			file_append(keyf, key)
	else:
		file_write(keyf, key)

def upstart_ensure( name ):
	"""Ensures that the given upstart service is running, restarting it if necessary"""
	if sudo("status "+ name ).find("/running") >= 0:
		sudo("restart " + name)
	else:
		sudo("start " + name)

# EOF - vim: ts=4 sw=4 noet
