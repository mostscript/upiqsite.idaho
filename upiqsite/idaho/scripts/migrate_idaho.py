"""
Copy project content, ideally without invoking OFS magic, but instead using
ZEXP -- should preserve UUIDs.

Site-wide stuff:
  * ~~ Site policy: upiqsite.idaho -> uu.projectsite
  * ~~ Re-index portal_catalog?
  * ~~ Copy project rosters.
  * Set site_url property in portal_properties/site_properties
  * Project schemas: form definitions and field group schemas to schema saver
  * Prime site data point cache (warm)
    * We need updated URLs anyway
  * Re-index uid_catalog?

"""

import time

from Products.CMFPlone.factory import addPloneSite
from Products.PlonePAS.Extensions.Install import activatePluginInterfaces
import transaction
from zope.component.hooks import setSite

from collective.teamwork.user.groups import Groups
from collective.teamwork.user.interfaces import IWorkspaceRoster
from collective.teamwork.user.members import SiteMembers
from collective.teamwork.utils import group_workspace, get_workspaces


TARGET = 'idaho'

POLICY = 'upiqsite.idaho:default'

VHOSTBASE = '/VirtualHostBase/https/teamspace1.upiq.org'

PROJECTS = (
    'idaho-medical-home-demonstration',
    'idaho-immunization-lc',
    'idaho-depression-screening-lc',
    'idaho-obesity-lc',
    'idaho-transitions',
    'demo-project-gina',
    'idaho-adhd-lc',
    )


def commit(context, msg):
    txn = transaction.get()
    # Undo path, if you want to use it, unfortunately is site-specific,
    # so use the hostname and VirtualHostMonster path used to access the
    # Application root containing all Plone sites:
    path = '/'.join(context.getPhysicalPath())
    if VHOSTBASE:
        txn.note('%s%s' % (VHOSTBASE, path))
    msg = '%s -- for %s' % (msg or 'Scripted action', path)
    txn.note(msg)
    txn.commit()


def create_target_site(app, name):
    return addPloneSite(app, name, extension_ids=(POLICY,))


def copyproject(source, targetsite):
    """Given source project and target site, copy project to site"""
    name = source.getId()
    copy = source._getCopy(targetsite)
    copy._setId(name)
    targetsite._setObject(name, copy, suppress_events=True)


def reindex_site(site):
    site.portal_catalog.clearFindAndRebuild()


def copy_pas_plugin(source_uf, target_uf, name):
    _plugin = getattr(source_uf, name)._getCopy(target_uf)
    _plugin._setId(name)
    target_uf._setObject(name, _plugin)
    activatePluginInterfaces(target_uf.__parent__, name)


def copy_pas_users_groups(source, target):
    source_uf = source.acl_users
    target_uf = target.acl_users
    names = ['source_users', 'source_groups']
    for name in names:
        target_uf._delObject(name, suppress_events=True)
        copy_pas_plugin(source_uf, target_uf, name)


def trim_groups(site):
    ignore = (
        'Administrators',
        'AuthenticatedUsers',
        'Site Administrators',
        'Reviewers',
        )
    groups = Groups(site)
    names = [group.name for group in groups.values()]
    trimmed = []
    for groupname in names:
        if groupname in ignore:
            continue
        workspace = group_workspace(groupname)
        if workspace is None:
            groups.remove(groupname)
            trimmed.append(groupname)
    assert len(names) > len(trimmed)  # there is still something left
    print 'Removed %s (unused) groups out of %s.' % (len(trimmed), len(names))


def all_workspace_users(site):
    """return a set of all workspace users"""
    r = set()
    all_workspaces = get_workspaces(site)
    for workspace in all_workspaces:
        roster = IWorkspaceRoster(workspace)
        r.update(roster.keys())
    return r


def trim_users(site):
    known = all_workspace_users(site)
    members = SiteMembers(site)
    orig = list(members)
    removed = []
    for username in list(members):
        if username not in known:
            del(members[username])
            removed.append(username)
    print 'Removed %s users ununsed of %s' % (len(removed), len(orig))


def trim_users_groups(site):
    trim_groups(site)
    trim_users(site)


def main(app):
    start = time.time()
    source = app.qiteamspace
    if TARGET not in app.objectIds():
        print 'Making target site...'
        target = create_target_site(app, TARGET)
    else:
        target = app[TARGET]
    print '\t--Since start: %s' % (time.time() - start)
    setSite(target)
    # pass 1: get content
    print 'Copying projects from source %s to target %s' % (
        source,
        target,
        )
    for name in PROJECTS:
        source_project = source[name]
        copyproject(source_project, targetsite=target)
    print '\t--Since start: %s' % (time.time() - start)
    # pass 2: index content
    print 'Reindexing content...'
    reindex_site(target)
    print '\t--Since start: %s' % (time.time() - start)
    # pass 3: copy all PAS users, groups
    print 'Copying PAS users and groups...'
    copy_pas_users_groups(source, target)
    print '\t--Since start: %s' % (time.time() - start)
    # pass 4: trim users and groups not belonging to workspaces:
    print 'Trimming users and groups...'
    trim_users_groups(target)
    print '\t--Since start: %s' % (time.time() - start)
    print 'Committing transaction...'
    #commit(target, 'Copied Idaho site content/data.')


if __name__ == '__main__' and 'app' in locals():
    main(app)  # noqa
