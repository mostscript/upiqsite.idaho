"""
Copy project content, ideally without invoking OFS magic, but instead using
ZEXP -- should preserve UUIDs.

Site-wide stuff:
  * ~~ Site policy: upiqsite.idaho -> uu.projectsite
  * ~~ Re-index portal_catalog?
  * ~~ Copy project rosters.
  * ~~ verify site_url property in portal_properties/site_properties
  * ~~ Project schemas: form definition, field group schemas to schema saver
  * ~~ Prime site data point cache (warm)

"""

import itertools
import time

from Products.CMFPlone.factory import addPloneSite
from Products.PlonePAS.Extensions.Install import activatePluginInterfaces
import transaction
from zope.component import queryUtility
from zope.component.hooks import setSite

from collective.teamwork.user.groups import Groups
from collective.teamwork.user.interfaces import IWorkspaceRoster
from collective.teamwork.user.members import SiteMembers
from collective.teamwork.utils import group_workspace, get_workspaces

from uu.formlibrary.handlers import definition_schema_handler
from uu.formlibrary.measure.cache import DataPointCache
from uu.dynamicschema.interfaces import ISchemaSaver, DEFAULT_SIGNATURE
from uu.formlibrary.interfaces import DEFINITION_TYPE, FIELD_GROUP_TYPE


DEFN_QUERY = {
    'portal_type': {
        'query': (DEFINITION_TYPE, FIELD_GROUP_TYPE),
        'operator': 'or',
        }
    }

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


def load_schemas(site):
    saver = queryUtility(ISchemaSaver)
    _get = lambda brain: brain._unrestrictedGetObject()
    r = site.portal_catalog.unrestrictedSearchResults(DEFN_QUERY)
    _added = 0
    for content in itertools.imap(_get, r):
        if not content.entry_schema.strip():
            continue
        signature = saver.signature(content.entry_schema)
        if signature == DEFAULT_SIGNATURE:
            continue
        if signature not in saver:
            definition_schema_handler(content, None)
            signature = content.signature  # sign. may have changed...
            _added += 1
        assert signature in saver
        print 'Schema provider %s, signature %s' % (content, signature)
    print '\tAdded %s schemas for %s schema providers' % (_added, len(r))


def warm_datapoints(site):
    cache = DataPointCache(site)
    cache.warm()


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
    # verify site_url is set as property:
    _prop = target.portal_properties.site_properties.getProperty
    assert _prop('site_url') == 'https://projects.ihawcc.org'
    # -- get content
    print 'Copying projects from source %s to target %s' % (
        source,
        target,
        )
    for name in PROJECTS:
        source_project = source[name]
        copyproject(source_project, targetsite=target)
    print '\t--Since start: %s' % (time.time() - start)
    # -- index content
    print 'Reindexing content...'
    reindex_site(target)
    print '\t--Since start: %s' % (time.time() - start)
    # -- copy all PAS users, groups
    print 'Copying PAS users and groups...'
    copy_pas_users_groups(source, target)
    print '\t--Since start: %s' % (time.time() - start)
    # -- trim users and groups not belonging to workspaces:
    print 'Trimming users and groups...'
    trim_users_groups(target)
    print '\t--Since start: %s' % (time.time() - start)
    # -- Populate schemas into local schema saver utility from all providers
    #    (form definitions and contained field groups)
    print 'Populating schema saver...'
    load_schemas(target)
    print '\t--Since start: %s' % (time.time() - start)
    # -- Warm data point cache:
    print 'Warming data point cache...'
    warm_datapoints(target)
    print '\t--Since start: %s' % (time.time() - start)
    # -- commmit transaction:
    print 'Committing transaction...'
    #commit(target, 'Copied Idaho site content/data.')
    print '\t--Since start: %s' % (time.time() - start)


if __name__ == '__main__' and 'app' in locals():
    main(app)  # noqa
