import transaction
from zope.component.hooks import setSite
import ZODB

BEFORE_CONFIG = """
    %import relstorage
    %import zc.beforestorage

    <before>
      before 2016-03-16T12:00:00
      <relstorage>
          pack-gc true
          <postgresql>
              dsn dbname=plone_zodb host=/home/qi/live/app/var/postgres port=5432
          </postgresql>
          blob-dir /home/qi/live/app/var/blobstorage
          shared-blob-dir true
      </relstorage>
    </before>
"""  # noqa


def normalize_path(base, path):
    if path.startswith('/'):
        path = path[1:]
    if base.startswith('/'):
        base = base[1:]
    if path.startswith(base):
        path = path[len(base) + 1:]
    return path


def get_entries(context):
    base_path = '/'.join(context.getPhysicalPath())
    catalog = context.portal_catalog
    project = context['adolescent-immunizations']
    q = {
        'path': '/'.join(project.getPhysicalPath()),
        'portal_type': 'uu.formlibrary.multiform',
        'Title': 'Baseline'
    }
    return map(
        lambda brain: normalize_path(base_path, brain.getPath()),
        list(catalog.unrestrictedSearchResults(q))
        )


def get_definition(context, path):
    return context.unrestrictedTraverse(path)


def restore_definition(source, target, path):
    """
    Given source, target sites, restore (schema, styles, rules of) definition.
    """
    setSite(source)
    source_definition = get_definition(source, path)
    schema_xml = source_definition.entry_schema
    styles = source_definition.form_css or ''
    rules = source_definition.field_rules or u'{}'
    setSite(target)
    target_definition = get_definition(target, path)
    target_definition.entry_schema = schema_xml
    target_definition.form_css = styles
    target_definition.field_rules = rules


def restore_form(source, target, path):
    """
    Given source, target sites, replace content at path, or create if it
    does not exist, using ZEXP.
    """
    setSite(source)
    source_content = source.unrestrictedTraverse(path)
    name = source_content.getId()
    zexp = source_content._p_jar.exportFile(source_content._p_oid)
    zexp.seek(0)
    setSite(target)
    container = target.unrestrictedTraverse('/'.join(path.split('/')[:-1]))
    try:
        existing_content = target.unrestrictedTraverse(path)  # noqa
        # remove possibly tainted newer copy, replace with older below...
        container.manage_delObjects([name])
    except KeyError:
        pass
    target_content = container._p_jar.importFile(zexp)
    target_content._setId(name)
    container._setObject(name, target_content)
    target_content.reindexObject()
    zexp.close()


def restore_forms(source, target):
    paths = get_entries(source)
    for path in paths:
        restore_form(source, target, path)


def main(app):
    before_storage = ZODB.config.storageFromString(BEFORE_CONFIG)
    before_db = ZODB.DB(before_storage)
    before_conn = before_db.open()
    root = before_conn.root
    app2 = root._root['Application']
    target_site = app.idaho     # noqa, current DB
    source_site = app2.idaho    # before snapshot
    defn_path = 'adolescent-immunizations/form-library/adolescent-immunizations-chart-audit-form'  # noqa
    restore_definition(source_site, target_site, defn_path)
    restore_forms(source_site, target_site)
    txn = transaction.get()
    txn.note(
        'Re-imported definition schema, baseline forms for IHAWCC '
        'from earlier snapshot via beforestorage/ZEXP.  (SDU)'
        )
    txn.commit()


if __name__ == '__main__' and 'app' in locals():
    main(app)  # noqa

