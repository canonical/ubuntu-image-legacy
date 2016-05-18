import gettext

catalog = gettext.Catalog("ubuntu-image", fallback=gettext.NullTranslations)

_ = catalog.gettext

__all__ = ('catalog', '_')
