import contextlib
import os
import webbrowser
from functools import partial
from typing import (
    Dict,
    List,
    Literal,
    NamedTuple,
    Optional,
    Protocol,
    Sequence,
    Tuple,
)

from packaging.version import parse as parse_version
from qtpy.QtCore import QSize, Qt, QTimer, Signal, Slot
from qtpy.QtGui import (
    QAction,
    QActionGroup,
    QFont,
    QKeySequence,
    QShortcut,
)
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from superqt import QCollapsible, QElidingLabel

from napari_plugin_manager.qt_package_installer import (
    InstallerActions,
    InstallerQueue,
    InstallerTools,
    ProcessFinishedData,
)
from napari_plugin_manager.qt_widgets import ClickableLabel
from napari_plugin_manager.utils import is_conda_package

CONDA = 'Conda'
PYPI = 'PyPI'


class BasePackageMetadata(Protocol):
    """Protocol class defining the minimum atributtes/properties needed for package metadata."""

    @property
    def metadata_version(self) -> str:
        pass

    @property
    def name(self) -> str:
        pass

    @property
    def version(self) -> str:
        pass

    @property
    def summary(self) -> str:
        pass

    @property
    def home_page(self) -> str:
        pass

    @property
    def author(self) -> str:
        pass

    @property
    def license(self) -> str:
        pass


class _BasePackageMetadata(NamedTuple):
    metadata_version: str
    name: str
    version: str
    summary: str
    home_page: str
    author: str
    license: str


class BaseProjectInfoVersions(NamedTuple):
    metadata: _BasePackageMetadata
    display_name: str
    pypi_versions: List[str]
    conda_versions: List[str]


class BasePluginListItem(QFrame):
    """
    An entry in the plugin dialog.

    This will include the package name, summary,
    author, source, version, and buttons to update, install/uninstall, etc.

    Make sure to implement all the methods that raise `NotImplementedError` over a subclass.
    Details are available in each method docstring.
    """

    # This should be set to the name of package that handles plugins
    # e.g `napari` for napari
    BASE_PACKAGE_NAME = ''

    # item, package_name, action_name, version, installer_choice
    actionRequested = Signal(QListWidgetItem, str, object, str, object)

    def __init__(
        self,
        item: QListWidgetItem,
        package_name: str,
        display_name: str,
        version: str = '',
        url: str = '',
        summary: str = '',
        author: str = '',
        license: str = "UNKNOWN",  # noqa: A002
        *,
        plugin_name: Optional[str] = None,
        parent: QWidget = None,
        enabled: bool = True,
        installed: bool = False,
        plugin_api_version=1,
        versions_conda: Optional[List[str]] = None,
        versions_pypi: Optional[List[str]] = None,
        prefix=None,
    ) -> None:
        super().__init__(parent)
        self.prefix = prefix
        self.item = item
        self.url = url
        self.name = package_name
        self.plugin_api_version = plugin_api_version
        self._version = version
        self._versions_conda = versions_conda
        self._versions_pypi = versions_pypi
        self.setup_ui(enabled)

        if package_name == display_name:
            name = package_name
        else:
            name = f"{display_name} <small>({package_name})</small>"

        self.plugin_name.setText(name)

        if len(versions_pypi) > 0:
            self._populate_version_dropdown(PYPI)
        else:
            self._populate_version_dropdown(CONDA)

        mod_version = version.replace('.', '․')  # noqa: RUF001
        self.version.setWordWrap(True)
        self.version.setText(mod_version)
        self.version.setToolTip(version)

        if summary:
            self.summary.setText(summary)

        if author:
            self.package_author.setText(author)

        self.package_author.setWordWrap(True)
        self.cancel_btn.setVisible(False)

        self._handle_plugin_api_version(plugin_api_version)
        self._set_installed(installed, package_name)
        self._populate_version_dropdown(self.get_installer_source())

    def _warning_icon(self, color=None, opacity=None):
        raise NotImplementedError

    def _collapsed_icon(self, color=None, opacity=None):
        raise NotImplementedError

    def _expanded_icon(self, color=None, opacity=None):
        raise NotImplementedError

    def _warning_tooltip(self):
        raise NotImplementedError

    def _trans(self, *args, **kwargs):
        raise NotImplementedError

    def _is_main_app_conda_package(self):
        return is_conda_package(self.BASE_PACKAGE_NAME)

    def _set_installed(self, installed: bool, package_name):
        if installed:
            if is_conda_package(package_name):
                self.source.setText(CONDA)

            self.enabled_checkbox.show()
            self.action_button.setText(self._trans("Uninstall"))
            self.action_button.setObjectName("remove_button")
            self.info_choice_wdg.hide()
            self.install_info_button.addWidget(self.info_widget)
            self.info_widget.show()
        else:
            self.enabled_checkbox.hide()
            self.action_button.setText(self._trans("Install"))
            self.action_button.setObjectName("install_button")
            self.info_widget.hide()
            self.install_info_button.addWidget(self.info_choice_wdg)
            self.info_choice_wdg.show()

    def _handle_plugin_api_version(self, plugin_api_version):
        raise NotImplementedError

    def set_status(self, icon=None, text=''):
        """Set the status icon and text. next to the package name."""
        if icon:
            self.status_icon.setPixmap(icon)

        if text:
            self.status_label.setText(text)

        self.status_icon.setVisible(bool(icon))
        self.status_label.setVisible(bool(text))

    def set_busy(
        self,
        text: str,
        action_name: Optional[
            Literal['install', 'uninstall', 'cancel', 'upgrade']
        ] = None,
    ):
        """Updates status text and what buttons are visible when any button is pushed.

        Parameters
        ----------
        text: str
            The new string to be displayed as the status.
        action_name: str
            The action of the button pressed.

        """
        self.item_status.setText(text)
        if action_name == 'upgrade':
            self.cancel_btn.setVisible(True)
            self.action_button.setVisible(False)
        elif action_name in {'uninstall', 'install'}:
            self.action_button.setVisible(False)
            self.cancel_btn.setVisible(True)
        elif action_name == 'cancel':
            self.action_button.setVisible(True)
            self.action_button.setDisabled(False)
            self.cancel_btn.setVisible(False)
        else:  # pragma: no cover
            raise ValueError(f"Not supported {action_name}")

    def setup_ui(self, enabled=True):
        """Define the layout of the PluginListItem"""
        # Enabled checkbox
        self.enabled_checkbox = QCheckBox(self)
        self.enabled_checkbox.setChecked(enabled)
        self.enabled_checkbox.setToolTip(self._trans("enable/disable"))
        self.enabled_checkbox.setText("")
        self.enabled_checkbox.stateChanged.connect(self._on_enabled_checkbox)

        sizePolicy = QSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(
            self.enabled_checkbox.sizePolicy().hasHeightForWidth()
        )
        self.enabled_checkbox.setSizePolicy(sizePolicy)
        self.enabled_checkbox.setMinimumSize(QSize(20, 0))

        # Plugin name
        self.plugin_name = ClickableLabel(self)  # To style content
        font_plugin_name = QFont()
        font_plugin_name.setPointSize(15)
        font_plugin_name.setUnderline(True)
        self.plugin_name.setFont(font_plugin_name)

        # Status
        self.status_icon = QLabel(self)
        self.status_icon.setVisible(False)
        self.status_label = QLabel(self)
        self.status_label.setVisible(False)

        if self.url and self.url != 'UNKNOWN':
            # Do not want to highlight on hover unless there is a website.
            self.plugin_name.setObjectName('plugin_name_web')
        else:
            self.plugin_name.setObjectName('plugin_name')

        sizePolicy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(
            self.plugin_name.sizePolicy().hasHeightForWidth()
        )
        self.plugin_name.setSizePolicy(sizePolicy)

        # Warning icon
        icon = self._warning_icon()
        self.warning_tooltip = self._warning_tooltip()

        self.warning_tooltip.setPixmap(icon.pixmap(15, 15))
        self.warning_tooltip.setVisible(False)

        # Item status
        self.item_status = QLabel(self)
        self.item_status.setObjectName("small_italic_text")
        self.item_status.setSizePolicy(sizePolicy)

        # Summary
        self.summary = QElidingLabel(parent=self)
        self.summary.setObjectName('summary_text')
        self.summary.setWordWrap(True)

        font_summary = QFont()
        font_summary.setPointSize(10)
        self.summary.setFont(font_summary)

        sizePolicy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        sizePolicy.setHorizontalStretch(1)
        sizePolicy.setVerticalStretch(0)
        self.summary.setSizePolicy(sizePolicy)
        self.summary.setContentsMargins(0, -2, 0, -2)

        # Package author
        self.package_author = QElidingLabel(self)
        self.package_author.setObjectName('author_text')
        self.package_author.setWordWrap(True)
        self.package_author.setSizePolicy(sizePolicy)

        # Update button
        self.update_btn = QPushButton('Update', self)
        self.update_btn.setObjectName("install_button")
        self.update_btn.setVisible(False)
        self.update_btn.clicked.connect(self._update_requested)
        sizePolicy.setRetainSizeWhenHidden(True)
        sizePolicy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.update_btn.setSizePolicy(sizePolicy)
        self.update_btn.clicked.connect(self._update_requested)

        # Action Button
        self.action_button = QPushButton(self)
        self.action_button.setFixedWidth(70)
        sizePolicy1 = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.action_button.setSizePolicy(sizePolicy1)
        self.action_button.clicked.connect(self._action_requested)

        # Cancel
        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.setObjectName("remove_button")
        self.cancel_btn.setSizePolicy(sizePolicy)
        self.cancel_btn.setFixedWidth(70)
        self.cancel_btn.clicked.connect(self._cancel_requested)

        # Collapsible button
        coll_icon = self._collapsed_icon(color='white')
        exp_icon = self._expanded_icon(color='white')

        self.install_info_button = QCollapsible(
            "Installation Info", collapsedIcon=coll_icon, expandedIcon=exp_icon
        )
        self.install_info_button.setLayoutDirection(
            Qt.RightToLeft
        )  # Make icon appear on the right
        self.install_info_button.setObjectName("install_info_button")
        self.install_info_button.setFixedWidth(180)
        self.install_info_button.content().layout().setContentsMargins(
            0, 0, 0, 0
        )
        self.install_info_button.content().setContentsMargins(0, 0, 0, 0)
        self.install_info_button.content().layout().setSpacing(0)
        self.install_info_button.layout().setContentsMargins(0, 0, 0, 0)
        self.install_info_button.layout().setSpacing(2)
        self.install_info_button.setSizePolicy(sizePolicy)

        # Information widget for available packages
        self.info_choice_wdg = QWidget(self)
        self.info_choice_wdg.setObjectName('install_choice')

        self.source_choice_text = QLabel('Source:')
        self.version_choice_text = QLabel('Version:')
        self.source_choice_dropdown = QComboBox()
        self.version_choice_dropdown = QComboBox()

        if self._is_main_app_conda_package() and self._versions_conda:
            self.source_choice_dropdown.addItem(CONDA)

        if self._versions_pypi:
            self.source_choice_dropdown.addItem(PYPI)

        source = self.get_installer_source()
        self.source_choice_dropdown.setCurrentText(source)
        self._populate_version_dropdown(source)
        self.source_choice_dropdown.currentTextChanged.connect(
            self._populate_version_dropdown
        )

        # Information widget for installed packages
        self.info_widget = QWidget(self)
        self.info_widget.setLayoutDirection(Qt.LeftToRight)
        self.info_widget.setObjectName("info_widget")
        self.info_widget.setFixedWidth(180)

        self.source_text = QLabel('Source:')
        self.source = QLabel(PYPI)
        self.version_text = QLabel('Version:')
        self.version = QElidingLabel()
        self.version.setWordWrap(True)

        info_layout = QGridLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setVerticalSpacing(0)
        info_layout.addWidget(self.source_text, 0, 0)
        info_layout.addWidget(self.source, 1, 0)
        info_layout.addWidget(self.version_text, 0, 1)
        info_layout.addWidget(self.version, 1, 1)
        self.info_widget.setLayout(info_layout)

        # Error indicator
        self.error_indicator = QPushButton()
        self.error_indicator.setObjectName("warning_icon")
        self.error_indicator.setCursor(Qt.CursorShape.PointingHandCursor)
        self.error_indicator.hide()

        # region - Layout
        # -----------------------------------------------------------------
        layout = QHBoxLayout()
        layout.setSpacing(2)
        layout_left = QVBoxLayout()
        layout_right = QVBoxLayout()
        layout_top = QHBoxLayout()
        layout_bottom = QHBoxLayout()
        layout_bottom.setSpacing(4)

        layout_left.addWidget(
            self.enabled_checkbox, alignment=Qt.AlignmentFlag.AlignTop
        )

        layout_right.addLayout(layout_top, 1)
        layout_right.addLayout(layout_bottom, 100)

        layout.addLayout(layout_left)
        layout.addLayout(layout_right)

        self.setLayout(layout)

        layout_top.addWidget(self.plugin_name)
        layout_top.addWidget(self.status_icon)
        layout_top.addWidget(self.status_label)
        layout_top.addWidget(self.item_status)
        layout_top.addStretch()

        layout_bottom.addWidget(
            self.summary, alignment=Qt.AlignmentFlag.AlignTop, stretch=3
        )
        layout_bottom.addWidget(
            self.package_author, alignment=Qt.AlignmentFlag.AlignTop, stretch=1
        )
        layout_bottom.addWidget(
            self.update_btn, alignment=Qt.AlignmentFlag.AlignTop
        )
        layout_bottom.addWidget(
            self.install_info_button, alignment=Qt.AlignmentFlag.AlignTop
        )
        layout_bottom.addWidget(
            self.action_button, alignment=Qt.AlignmentFlag.AlignTop
        )
        layout_bottom.addWidget(
            self.cancel_btn, alignment=Qt.AlignmentFlag.AlignTop
        )

        info_layout = QGridLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setVerticalSpacing(0)
        info_layout.addWidget(self.source_choice_text, 0, 0, 1, 1)
        info_layout.addWidget(self.source_choice_dropdown, 1, 0, 1, 1)
        info_layout.addWidget(self.version_choice_text, 0, 1, 1, 1)
        info_layout.addWidget(self.version_choice_dropdown, 1, 1, 1, 1)

        # endregion - Layout

        self.info_choice_wdg.setLayout(info_layout)
        self.info_choice_wdg.setLayoutDirection(Qt.LeftToRight)
        self.info_choice_wdg.setObjectName("install_choice_widget")
        self.info_choice_wdg.hide()

    def _populate_version_dropdown(self, source: Literal["PyPI", "Conda"]):
        """Display the versions available after selecting a source: pypi or conda."""
        if source == PYPI:
            versions = self._versions_pypi
        else:
            versions = self._versions_conda
        self.version_choice_dropdown.clear()
        for version in versions:
            self.version_choice_dropdown.addItem(version)

    def _on_enabled_checkbox(self, state: int):
        """Called with `state` when checkbox is clicked."""
        raise NotImplementedError

    def _cancel_requested(self):
        version = self.version_choice_dropdown.currentText()
        tool = self.get_installer_tool()
        self.actionRequested.emit(
            self.item, self.name, InstallerActions.CANCEL, version, tool
        )

    def _action_requested(self):
        version = self.version_choice_dropdown.currentText()
        tool = self.get_installer_tool()
        action = (
            InstallerActions.INSTALL
            if self.action_button.objectName() == 'install_button'
            else InstallerActions.UNINSTALL
        )
        self.actionRequested.emit(self.item, self.name, action, version, tool)

    def _update_requested(self):
        version = self.version_choice_dropdown.currentText()
        tool = self.get_installer_tool()
        self.actionRequested.emit(
            self.item, self.name, InstallerActions.UPGRADE, version, tool
        )

    def show_warning(self, message: str = ""):
        """Show warning icon and tooltip."""
        self.warning_tooltip.setVisible(bool(message))
        self.warning_tooltip.setToolTip(message)

    def get_installer_source(self):
        return (
            CONDA
            if self.source_choice_dropdown.currentText() == CONDA
            or is_conda_package(self.name)
            else PYPI
        )

    def get_installer_tool(self):
        return (
            InstallerTools.CONDA
            if self.source_choice_dropdown.currentText() == CONDA
            or is_conda_package(self.name, prefix=self.prefix)
            else InstallerTools.PIP
        )


class BaseQPluginList(QListWidget):
    """
    A list of plugins.

    Make sure to implement all the methods that raise `NotImplementedError` over a subclass.
    Details are available in each method docstring.
    """

    _SORT_ORDER_PREFIX = '0-'
    PLUGIN_LIST_ITEM_CLASS = BasePluginListItem

    def __init__(self, parent: QWidget, installer: InstallerQueue) -> None:
        super().__init__(parent)
        self.installer = installer
        self._remove_list = []
        self._data = []
        self._initial_height = None

        self.setSortingEnabled(True)

    def _trans(self, *args, **kwargs):
        raise NotImplementedError

    def count_visible(self) -> int:
        """Return the number of visible items.

        Visible items are the result of the normal `count` method minus
        any hidden items.
        """
        hidden = 0
        count = self.count()
        for i in range(count):
            item = self.item(i)
            hidden += item.isHidden()

        return count - hidden

    @Slot(tuple)
    def addItem(
        self,
        project_info: BaseProjectInfoVersions,
        installed=False,
        plugin_name=None,
        enabled=True,
        plugin_api_version=None,
    ):
        pkg_name = project_info.metadata.name
        # don't add duplicates
        if (
            self.findItems(pkg_name, Qt.MatchFlag.MatchFixedString)
            and not plugin_name
        ):
            return

        # including summary here for sake of filtering below.
        searchable_text = f"{pkg_name} {project_info.display_name} {project_info.metadata.summary}"
        item = QListWidgetItem(searchable_text, self)
        item.version = project_info.metadata.version
        super().addItem(item)
        widg = self.PLUGIN_LIST_ITEM_CLASS(
            item=item,
            package_name=pkg_name,
            display_name=project_info.display_name,
            version=project_info.metadata.version,
            url=project_info.metadata.home_page,
            summary=project_info.metadata.summary,
            author=project_info.metadata.author,
            license=project_info.metadata.license,
            parent=self,
            plugin_name=plugin_name,
            enabled=enabled,
            installed=installed,
            plugin_api_version=plugin_api_version,
            versions_conda=project_info.conda_versions,
            versions_pypi=project_info.pypi_versions,
        )
        item.widget = widg
        item.plugin_api_version = plugin_api_version
        item.setSizeHint(widg.sizeHint())
        self.setItemWidget(item, widg)

        if project_info.metadata.home_page:
            widg.plugin_name.clicked.connect(
                partial(webbrowser.open, project_info.metadata.home_page)
            )

        widg.actionRequested.connect(self.handle_action)
        item.setSizeHint(item.widget.size())
        if self._initial_height is None:
            self._initial_height = item.widget.size().height()

        widg.install_info_button.setDuration(0)
        widg.install_info_button.toggled.connect(
            lambda: self._resize_pluginlistitem(item)
        )

    def removeItem(self, name):
        count = self.count()
        for i in range(count):
            item = self.item(i)
            if item.widget.name == name:
                self.takeItem(i)
                break

    def refreshItem(self, name, version=None):
        count = self.count()
        for i in range(count):
            item = self.item(i)
            if item.widget.name == name:
                if version is not None:
                    item.version = version
                    mod_version = version.replace('.', '․')  # noqa: RUF001
                    item.widget.version.setText(mod_version)
                    item.widget.version.setToolTip(version)
                item.widget.set_busy('', InstallerActions.CANCEL)
                if item.text().startswith(self._SORT_ORDER_PREFIX):
                    item.setText(item.text()[len(self._SORT_ORDER_PREFIX) :])
                break

    def _resize_pluginlistitem(self, item):
        """Resize the plugin list item, especially after toggling QCollapsible."""
        if item.widget.install_info_button.isExpanded():
            item.widget.setFixedHeight(self._initial_height + 35)
        else:
            item.widget.setFixedHeight(self._initial_height)

        item.setSizeHint(QSize(0, item.widget.height()))

    def _handle_plugin_api_version_action(self, widget, action_name):
        raise NotImplementedError

    def handle_action(
        self,
        item: QListWidgetItem,
        pkg_name: str,
        action_name: InstallerActions,
        version: Optional[str] = None,
        installer_choice: Optional[str] = None,
    ):
        """Determine which action is called (install, uninstall, update, cancel).
        Update buttons appropriately and run the action."""
        widget = item.widget
        tool = installer_choice or widget.get_installer_tool()
        self._remove_list.append((pkg_name, item))
        self._warn_dialog = None
        if not item.text().startswith(self._SORT_ORDER_PREFIX):
            item.setText(f"{self._SORT_ORDER_PREFIX}{item.text()}")

        self._handle_plugin_api_version_action(widget, action_name)

        if action_name == InstallerActions.INSTALL:
            if version:
                pkg_name += (
                    f"=={item.widget.version_choice_dropdown.currentText()}"
                )
            widget.set_busy(self._trans("installing..."), action_name)

            job_id = self.installer.install(
                tool=tool,
                pkgs=[pkg_name],
                # origins="TODO",
            )
            widget.setProperty("current_job_id", job_id)
            if self._warn_dialog:
                self._warn_dialog.exec_()
            self.scrollToTop()

        if action_name == InstallerActions.UPGRADE:
            if hasattr(item, 'latest_version'):
                pkg_name += f"=={item.latest_version}"

            widget.set_busy(self._trans("updating..."), action_name)
            widget.update_btn.setDisabled(True)
            widget.action_button.setDisabled(True)

            job_id = self.installer.upgrade(
                tool=tool,
                pkgs=[pkg_name],
                # origins="TODO",
            )
            widget.setProperty("current_job_id", job_id)
            if self._warn_dialog:
                self._warn_dialog.exec_()
            self.scrollToTop()

        elif action_name == InstallerActions.UNINSTALL:
            widget.set_busy(self._trans("uninstalling..."), action_name)
            widget.update_btn.setDisabled(True)
            job_id = self.installer.uninstall(
                tool=tool,
                pkgs=[pkg_name],
                # origins="TODO",
                # upgrade=False,
            )
            widget.setProperty("current_job_id", job_id)
            if self._warn_dialog:
                self._warn_dialog.exec_()
            self.scrollToTop()
        elif action_name == InstallerActions.CANCEL:
            widget.set_busy(self._trans("cancelling..."), action_name)
            try:
                job_id = widget.property("current_job_id")
                self.installer.cancel(job_id)
            finally:
                widget.setProperty("current_job_id", None)

    def set_data(self, data):
        self._data = data

    def is_running(self):
        return self.count() != len(self._data)

    def packages(self):
        return [self.item(idx).widget.name for idx in range(self.count())]

    @Slot(BasePackageMetadata, bool)
    def tag_outdated(self, metadata: BasePackageMetadata, is_available: bool):
        """Determines if an installed plugin is up to date with the latest version.
        If it is not, the latest version will be displayed on the update button.
        """
        if not is_available:
            return

        for item in self.findItems(
            metadata.name, Qt.MatchFlag.MatchStartsWith
        ):
            current = item.version
            latest = metadata.version
            is_marked_outdated = getattr(item, 'outdated', False)
            if parse_version(current) >= parse_version(latest):
                # currently is up to date
                if is_marked_outdated:
                    # previously marked as outdated, need to update item
                    # `outdated` state and hide item widget `update_btn`
                    item.outdated = False
                    widg = self.itemWidget(item)
                    widg.update_btn.setVisible(False)
                continue
            if is_marked_outdated:
                # already tagged it
                continue

            item.outdated = True
            item.latest_version = latest
            widg = self.itemWidget(item)
            widg.update_btn.setVisible(True)
            widg.update_btn.setText(
                self._trans("update (v{latest})", latest=latest)
            )

    def tag_unavailable(self, metadata: BasePackageMetadata):
        """
        Tag list items as unavailable for install with conda-forge.

        This will disable the item and the install button and add a warning
        icon with a hover tooltip.
        """
        for item in self.findItems(
            metadata.name, Qt.MatchFlag.MatchStartsWith
        ):
            widget = self.itemWidget(item)
            widget.show_warning(
                self._trans(
                    "Plugin not yet available for installation within the bundle application"
                )
            )
            widget.setObjectName("unavailable")
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.action_button.setEnabled(False)
            widget.warning_tooltip.setVisible(True)

    def filter(self, text: str, starts_with_chars: int = 1):
        """Filter items to those containing `text`."""
        if text:
            # PySide has some issues, so we compare using id
            # See: https://bugreports.qt.io/browse/PYSIDE-74
            flag = (
                Qt.MatchFlag.MatchStartsWith
                if len(text) <= starts_with_chars
                else Qt.MatchFlag.MatchContains
            )
            if len(text) <= starts_with_chars:
                flag = Qt.MatchFlag.MatchStartsWith
                queries = (text, f'napari-{text}')
            else:
                flag = Qt.MatchFlag.MatchContains
                queries = (text,)

            shown = {
                id(it)
                for query in queries
                for it in self.findItems(query, flag)
            }
            for i in range(self.count()):
                item = self.item(i)
                item.setHidden(id(item) not in shown)
        else:
            for i in range(self.count()):
                item = self.item(i)
                item.setHidden(False)


class BaseQtPluginDialog(QDialog):
    """
    A plugins dialog.

    The dialog shows two list of plugins:
        * A list for the already installed plugins and
        * A list for the plugins that could be installed

    It also counts with a space to show output related with the actions being done
    (installing/uninstalling/updating a plugin).

    Make sure to implement all the methods that raise `NotImplementedError` over a subclass.
    Details are available in each method docstring.
    """

    PACKAGE_METADATA_CLASS = _BasePackageMetadata
    PROJECT_INFO_VERSION_CLASS = BaseProjectInfoVersions
    PLUGIN_LIST_CLASS = BaseQPluginList
    BASE_PACKAGE_NAME = ''

    def __init__(self, parent=None, prefix=None) -> None:
        super().__init__(parent)

        self._parent = parent
        if (
            parent is not None
            and getattr(parent, '_plugin_dialog', None) is None
        ):
            self._parent._plugin_dialog = self

        self.already_installed = set()
        self.available_set = set()
        self._prefix = prefix
        self._first_open = True
        self._plugin_queue = []  # Store plugin data to be added
        self._plugin_data = []  # Store all plugin data
        self._filter_texts = []
        self._filter_idxs_cache = set()
        self._filter_timer = QTimer(self)
        self.worker = None

        # timer to avoid triggering a filter for every keystroke
        self._filter_timer.setInterval(140)  # ms
        self._filter_timer.timeout.connect(self.filter)
        self._filter_timer.setSingleShot(True)
        self._plugin_data_map = {}
        self._add_items_timer = QTimer(self)

        # Timer to avoid race conditions and incorrect count of plugins when
        # refreshing multiple times in a row. After click we disable the
        # `Refresh` button and re-enable it after 3 seconds.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(3000)  # ms
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._enable_refresh_button)

        # Add items in batches with a pause to avoid blocking the UI
        self._add_items_timer.setInterval(61)  # ms
        self._add_items_timer.timeout.connect(self._add_items)

        self.installer = InstallerQueue(parent=self, prefix=prefix)
        self.setWindowTitle(self._trans('Plugin Manager'))
        self._setup_ui()
        self.installer.set_output_widget(self.stdout_text)
        self.installer.started.connect(self._on_installer_start)
        self.installer.processFinished.connect(self._on_process_finished)
        self.installer.allFinished.connect(self._on_installer_all_finished)
        self.setAcceptDrops(True)

        if (
            parent is not None and parent._plugin_dialog is self
        ) or parent is None:
            self.refresh()
            self._setup_shortcuts()
            self._setup_theme_update()

    # region - Private methods
    # ------------------------------------------------------------------------
    def _enable_refresh_button(self):
        self.refresh_button.setEnabled(True)

    def _quit(self):
        self.close()
        with contextlib.suppress(AttributeError):
            self._parent.close(quit_app=True, confirm_need=True)

    def _setup_shortcuts(self):
        self._refresh_styles_action = QAction(
            self._trans('Refresh Styles'), self
        )
        self._refresh_styles_action.setShortcut('Ctrl+R')
        self._refresh_styles_action.triggered.connect(self._update_theme)
        self.addAction(self._refresh_styles_action)

        self._quit_action = QAction(self._trans('Exit'), self)
        self._quit_action.setShortcut('Ctrl+Q')
        self._quit_action.setMenuRole(QAction.QuitRole)
        self._quit_action.triggered.connect(self._quit)
        self.addAction(self._quit_action)

        self._close_shortcut = QShortcut(
            QKeySequence(Qt.CTRL | Qt.Key_W), self
        )
        self._close_shortcut.activated.connect(self.close)

    def _setup_theme_update(self):
        raise NotImplementedError

    def _update_theme(self, event):
        raise NotImplementedError

    def _on_installer_start(self):
        """Updates dialog buttons and status when installing a plugin."""
        self.cancel_all_btn.setVisible(True)
        self.working_indicator.show()
        self.process_success_indicator.hide()
        self.process_error_indicator.hide()
        self.refresh_button.setDisabled(True)

    def _on_process_finished(self, process_finished_data: ProcessFinishedData):
        action = process_finished_data['action']
        exit_code = process_finished_data['exit_code']
        pkg_names = [
            pkg.split('==')[0] for pkg in process_finished_data['pkgs']
        ]
        if action == InstallerActions.INSTALL:
            if exit_code == 0:
                for pkg_name in pkg_names:
                    if pkg_name in self.available_set:
                        self.available_set.remove(pkg_name)

                    self.available_list.removeItem(pkg_name)
                    self._add_installed(pkg_name)
                    self._tag_outdated_plugins()
            else:
                for pkg_name in pkg_names:
                    self.available_list.refreshItem(pkg_name)
        elif action == InstallerActions.UNINSTALL:
            if exit_code == 0:
                for pkg_name in pkg_names:
                    if pkg_name in self.already_installed:
                        self.already_installed.remove(pkg_name)

                    self.installed_list.removeItem(pkg_name)
                    self._add_to_available(pkg_name)
            else:
                for pkg_name in pkg_names:
                    self.installed_list.refreshItem(pkg_name)
        elif action == InstallerActions.UPGRADE:
            pkg_info = [
                (pkg.split('==')[0], pkg.split('==')[1])
                for pkg in process_finished_data['pkgs']
            ]
            for pkg_name, pkg_version in pkg_info:
                self.installed_list.refreshItem(pkg_name, version=pkg_version)
                self._tag_outdated_plugins()
        elif action in [InstallerActions.CANCEL, InstallerActions.CANCEL_ALL]:
            for pkg_name in pkg_names:
                self.installed_list.refreshItem(pkg_name)
                self.available_list.refreshItem(pkg_name)
                self._tag_outdated_plugins()

        self.working_indicator.hide()
        if exit_code:
            self.process_error_indicator.show()
        else:
            self.process_success_indicator.show()

    def _on_installer_all_finished(self, exit_codes):
        self.working_indicator.hide()
        self.cancel_all_btn.setVisible(False)
        self.close_btn.setDisabled(False)
        self.refresh_button.setDisabled(False)

        if not self.isVisible():
            if sum(exit_codes) > 0:
                self._show_warning(
                    self._trans(
                        'Plugin Manager: process completed with errors\n'
                    )
                )
            else:
                self._show_info(
                    self._trans('Plugin Manager: process completed\n')
                )

    def _add_to_available(self, pkg_name):
        self._add_items_timer.stop()
        self._plugin_queue.insert(0, self._plugin_data_map[pkg_name])
        self._add_items_timer.start()
        self._update_plugin_count()

    def _add_installed(self, pkg_name=None):
        raise NotImplementedError

    def _fetch_available_plugins(self, clear_cache: bool = False):
        raise NotImplementedError

    def _loading_gif(self):
        raise NotImplementedError

    def _on_bundle(self):
        raise NotImplementedError

    def _show_info(self, info):
        raise NotImplementedError

    def _show_warning(self, warning):
        raise NotImplementedError

    def _trans(self, *args, **kwargs):
        raise NotImplementedError

    def _is_main_app_conda_package(self):
        return is_conda_package(self.BASE_PACKAGE_NAME)

    def _setup_ui(self):
        """Defines the layout for the PluginDialog."""
        self.resize(900, 600)
        vlay_1 = QVBoxLayout(self)
        self.h_splitter = QSplitter(self)
        vlay_1.addWidget(self.h_splitter)
        self.h_splitter.setOrientation(Qt.Orientation.Horizontal)
        self.v_splitter = QSplitter(self.h_splitter)
        self.v_splitter.setOrientation(Qt.Orientation.Vertical)
        self.v_splitter.setMinimumWidth(500)

        installed = QWidget(self.v_splitter)
        lay = QVBoxLayout(installed)
        lay.setContentsMargins(0, 2, 0, 2)
        self.installed_label = QLabel(self._trans("Installed Plugins"))
        self.packages_filter = QLineEdit()
        self.packages_filter.setPlaceholderText(self._trans("filter..."))
        self.packages_filter.setMaximumWidth(350)
        self.packages_filter.setClearButtonEnabled(True)
        self.packages_filter.textChanged.connect(self._filter_timer.start)

        self.refresh_button = QPushButton(self._trans('Refresh'), self)
        self.refresh_button.setObjectName("refresh_button")
        self.refresh_button.setToolTip(
            self._trans(
                'This will clear and refresh the available and installed plugins lists.'
            )
        )
        self.refresh_button.clicked.connect(self._refresh_and_clear_cache)

        mid_layout = QVBoxLayout()
        horizontal_mid_layout = QHBoxLayout()
        horizontal_mid_layout.addWidget(self.packages_filter)
        horizontal_mid_layout.addStretch()
        horizontal_mid_layout.addWidget(self.refresh_button)
        mid_layout.addLayout(horizontal_mid_layout)
        # mid_layout.addWidget(self.packages_filter)
        mid_layout.addWidget(self.installed_label)
        lay.addLayout(mid_layout)

        self.installed_list = self.PLUGIN_LIST_CLASS(installed, self.installer)
        lay.addWidget(self.installed_list)

        uninstalled = QWidget(self.v_splitter)
        lay = QVBoxLayout(uninstalled)
        lay.setContentsMargins(0, 2, 0, 2)
        self.avail_label = QLabel(self._trans("Available Plugins"))
        mid_layout = QHBoxLayout()
        mid_layout.addWidget(self.avail_label)
        mid_layout.addStretch()
        lay.addLayout(mid_layout)
        self.available_list = self.PLUGIN_LIST_CLASS(
            uninstalled, self.installer
        )
        lay.addWidget(self.available_list)

        self.stdout_text = QTextEdit(self.v_splitter)
        self.stdout_text.setReadOnly(True)
        self.stdout_text.setObjectName("plugin_manager_process_status")
        self.stdout_text.hide()

        buttonBox = QHBoxLayout()
        self.working_indicator = QLabel(self._trans("loading ..."), self)
        sp = self.working_indicator.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        self.working_indicator.setSizePolicy(sp)
        self.process_error_indicator = QLabel(self)
        self.process_error_indicator.setObjectName("error_label")
        self.process_error_indicator.hide()
        self.process_success_indicator = QLabel(self)
        self.process_success_indicator.setObjectName("success_label")
        self.process_success_indicator.hide()
        mov = self._loading_gif()
        self.working_indicator.setMovie(mov)
        mov.start()

        visibility_direct_entry = not self._on_bundle()
        self.direct_entry_edit = QLineEdit(self)
        self.direct_entry_edit.installEventFilter(self)
        self.direct_entry_edit.returnPressed.connect(self._install_packages)
        self.direct_entry_edit.setVisible(visibility_direct_entry)
        self.direct_entry_btn = QToolButton(self)
        self.direct_entry_btn.setVisible(visibility_direct_entry)
        self.direct_entry_btn.clicked.connect(self._install_packages)
        self.direct_entry_btn.setText(self._trans("Install"))

        self._action_conda = QAction(self._trans('Conda'), self)
        self._action_conda.setCheckable(True)
        self._action_conda.triggered.connect(self._update_direct_entry_text)

        self._action_pypi = QAction(self._trans('pip'), self)
        self._action_pypi.setCheckable(True)
        self._action_pypi.triggered.connect(self._update_direct_entry_text)

        self._action_group = QActionGroup(self)
        self._action_group.addAction(self._action_pypi)
        self._action_group.addAction(self._action_conda)
        self._action_group.setExclusive(True)

        self._menu = QMenu(self)
        self._menu.addAction(self._action_conda)
        self._menu.addAction(self._action_pypi)

        if self._is_main_app_conda_package():
            self.direct_entry_btn.setPopupMode(QToolButton.MenuButtonPopup)
            self._action_conda.setChecked(True)
            self.direct_entry_btn.setMenu(self._menu)

        self.show_status_btn = QPushButton(self._trans("Show Status"), self)
        self.show_status_btn.setFixedWidth(100)

        self.cancel_all_btn = QPushButton(
            self._trans("cancel all actions"), self
        )
        self.cancel_all_btn.setObjectName("remove_button")
        self.cancel_all_btn.setVisible(False)
        self.cancel_all_btn.clicked.connect(self.installer.cancel_all)

        self.close_btn = QPushButton(self._trans("Close"), self)
        self.close_btn.clicked.connect(self.accept)
        self.close_btn.setObjectName("close_button")

        buttonBox.addWidget(self.show_status_btn)
        buttonBox.addWidget(self.working_indicator)
        buttonBox.addWidget(self.direct_entry_edit)
        buttonBox.addWidget(self.direct_entry_btn)
        if not visibility_direct_entry:
            buttonBox.addStretch()
        buttonBox.addWidget(self.process_success_indicator)
        buttonBox.addWidget(self.process_error_indicator)
        buttonBox.addSpacing(20)
        buttonBox.addWidget(self.cancel_all_btn)
        buttonBox.addSpacing(20)
        buttonBox.addWidget(self.close_btn)
        buttonBox.setContentsMargins(0, 0, 4, 0)
        vlay_1.addLayout(buttonBox)

        self.show_status_btn.setCheckable(True)
        self.show_status_btn.setChecked(False)
        self.show_status_btn.toggled.connect(self.toggle_status)

        self.v_splitter.setStretchFactor(1, 2)
        self.h_splitter.setStretchFactor(0, 2)

        self.packages_filter.setFocus()
        self._update_direct_entry_text()

    def _update_direct_entry_text(self):
        tool = (
            str(InstallerTools.CONDA)
            if self._action_conda.isChecked()
            else str(InstallerTools.PIP)
        )
        self.direct_entry_edit.setPlaceholderText(
            self._trans(
                "install with '{tool}' by name/url, or drop file...", tool=tool
            )
        )

    def _update_plugin_count(self):
        """Update count labels for both installed and available plugin lists.
        Displays also amount of visible plugins out of total when filtering.
        """
        installed_count = self.installed_list.count()
        installed_count_visible = self.installed_list.count_visible()
        if installed_count == installed_count_visible:
            self.installed_label.setText(
                self._trans(
                    "Installed Plugins ({amount})",
                    amount=installed_count,
                )
            )
        else:
            self.installed_label.setText(
                self._trans(
                    "Installed Plugins ({count}/{amount})",
                    count=installed_count_visible,
                    amount=installed_count,
                )
            )

        available_count = len(self._plugin_data) - self.installed_list.count()
        available_count = available_count if available_count >= 0 else 0
        available_count_visible = self.available_list.count_visible()
        if available_count == available_count_visible:
            self.avail_label.setText(
                self._trans(
                    "Available Plugins ({amount})",
                    amount=available_count,
                )
            )
        else:
            self.avail_label.setText(
                self._trans(
                    "Available Plugins ({count}/{amount})",
                    count=available_count_visible,
                    amount=available_count,
                )
            )

    def _install_packages(
        self,
        packages: Sequence[str] = (),
    ):
        if not packages:
            _packages = self.direct_entry_edit.text()
            packages = (
                [_packages] if os.path.exists(_packages) else _packages.split()
            )
            self.direct_entry_edit.clear()

        if packages:
            tool = (
                InstallerTools.CONDA
                if self._action_conda.isChecked()
                else InstallerTools.PIP
            )
            self.installer.install(tool, packages)

    def _tag_outdated_plugins(self):
        """Tag installed plugins that might be outdated."""
        for pkg_name in self.installed_list.packages():
            _data = self._plugin_data_map.get(pkg_name)
            if _data is not None:
                metadata, is_available_in_conda, _ = _data
                self.installed_list.tag_outdated(
                    metadata, is_available_in_conda
                )

    def _add_items(self):
        """
        Add items to the lists by `batch_size` using a timer to add a pause
        and prevent freezing the UI.
        """
        if len(self._plugin_queue) == 0:
            if (
                self.installed_list.count() + self.available_list.count()
                == len(self._plugin_data)
                and self.available_list.count() != 0
            ):
                self._add_items_timer.stop()
                if not self.isVisible():
                    self._show_info(
                        self._trans(
                            'Plugin Manager: All available plugins loaded\n'
                        )
                    )

            return

        batch_size = 2
        for _ in range(batch_size):
            data = self._plugin_queue.pop(0)
            metadata, is_available_in_conda, extra_info = data
            display_name = extra_info.get('display_name', metadata.name)
            if metadata.name in self.already_installed:
                self.installed_list.tag_outdated(
                    metadata, is_available_in_conda
                )
            else:
                if metadata.name not in self.available_set:
                    self.available_set.add(metadata.name)
                    self.available_list.addItem(
                        self.PROJECT_INFO_VERSION_CLASS(
                            display_name=display_name,
                            pypi_versions=extra_info['pypi_versions'],
                            conda_versions=extra_info['conda_versions'],
                            metadata=metadata,
                        )
                    )
                if self._on_bundle() and not is_available_in_conda:
                    self.available_list.tag_unavailable(metadata)

            if len(self._plugin_queue) == 0:
                self._tag_outdated_plugins()
                break

        if not self._filter_timer.isActive():
            self.filter(None, skip=True)

    def _handle_yield(self, data: Tuple[BasePackageMetadata, bool, Dict]):
        """Output from a worker process.

        Includes information about the plugin, including available versions on conda and pypi.

        The data is stored but the actual items are added via a timer in the `_add_items`
        method to prevent the UI from freezing by adding all items at once.
        """
        self._plugin_data.append(data)
        self._plugin_queue.append(data)
        self._filter_texts = [
            f"{i[0].name} {i[-1].get('display_name', '')} {i[0].summary}".lower()
            for i in self._plugin_data
        ]
        metadata, _, _ = data
        self._plugin_data_map[metadata.name] = data
        self.available_list.set_data(self._plugin_data)

    def _search_in_available(self, text):
        idxs = []
        for idx, item in enumerate(self._filter_texts):
            if text.lower() in item and idx not in self._filter_idxs_cache:
                idxs.append(idx)
                self._filter_idxs_cache.add(idx)

        return idxs

    def _refresh_and_clear_cache(self):
        self.refresh(clear_cache=True)

    # endregion - Private methods

    # region - Qt overrides
    # ------------------------------------------------------------------------
    def closeEvent(self, event):
        if self._parent is not None:
            plugin_dialog = getattr(self._parent, '_plugin_dialog', self)
            if self != plugin_dialog:
                self.destroy(True, True)
                super().closeEvent(event)
            else:
                plugin_dialog.hide()
        else:
            super().closeEvent(event)

    def dragEnterEvent(self, event):
        event.accept()

    def dropEvent(self, event):
        md = event.mimeData()
        if md.hasUrls():
            files = [url.toLocalFile() for url in md.urls()]
            self.direct_entry_edit.setText(files[0])
            return True

        return super().dropEvent(event)

    def exec_(self):
        plugin_dialog = getattr(self._parent, '_plugin_dialog', self)
        if plugin_dialog != self:
            self.close()

        plugin_dialog.setModal(True)
        plugin_dialog.show()

        if self._first_open:
            self._update_theme(None)
            self._first_open = False

    def hideEvent(self, event):
        self.packages_filter.clear()
        self.toggle_status(False)
        super().hideEvent(event)

    # endregion - Qt overrides

    # region - Public methods
    # ------------------------------------------------------------------------
    def filter(self, text: Optional[str] = None, skip=False) -> None:
        """Filter by text or set current text as filter."""
        if text is None:
            text = self.packages_filter.text()
        else:
            self.packages_filter.setText(text)

        if not skip and self.available_list.is_running() and len(text) >= 1:
            items = [
                self._plugin_data[idx]
                for idx in self._search_in_available(text)
            ]
            if items:
                for item in items:
                    if item in self._plugin_queue:
                        self._plugin_queue.remove(item)

                self._plugin_queue = items + self._plugin_queue

        self.installed_list.filter(text)
        self.available_list.filter(text)
        self._update_plugin_count()

    def refresh(self, clear_cache: bool = False):
        self.refresh_button.setDisabled(True)

        if self.worker is not None:
            self.worker.quit()

        if self._add_items_timer.isActive():
            self._add_items_timer.stop()

        self._filter_texts = []
        self._plugin_queue = []
        self._plugin_data = []
        self._plugin_data_map = {}

        self.installed_list.clear()
        self.available_list.clear()
        self.already_installed = set()
        self.available_set = set()

        self._add_installed()
        self._fetch_available_plugins(clear_cache=clear_cache)

        self._refresh_timer.start()

    def toggle_status(self, show=None):
        show = not self.stdout_text.isVisible() if show is None else show
        if show:
            self.show_status_btn.setText(self._trans("Hide Status"))
            self.stdout_text.show()
        else:
            self.show_status_btn.setText(self._trans("Show Status"))
            self.stdout_text.hide()

    def set_prefix(self, prefix):
        self._prefix = prefix
        self.installer._prefix = prefix
        for idx in range(self.available_list.count()):
            item = self.available_list.item(idx)
            item.widget.prefix = prefix

        for idx in range(self.installed_list.count()):
            item = self.installed_list.item(idx)
            item.widget.prefix = prefix

    # endregion - Public methods