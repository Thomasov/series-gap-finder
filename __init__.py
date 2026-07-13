__license__ = 'GPL v3'

from calibre.customize import InterfaceActionBase


class SeriesGapFinder(InterfaceActionBase):
    '''
    Finds books missing from the series you own, using series data
    from the free Hardcover.app GraphQL API.
    '''
    name = 'Series Gap Finder'
    description = ('Find missing books in the series you own, '
                   'using series data from Hardcover.app')
    supported_platforms = ['windows', 'osx', 'linux']
    author = 'Thomas Overfield'
    version = (1, 0, 5)
    minimum_calibre_version = (6, 0, 0)

    actual_plugin = 'calibre_plugins.series_gap_finder.ui:SeriesGapFinderAction'

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.series_gap_finder.config import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()
