"""Editorial desktop themes for the Planora academic-planning workspace."""


LIGHT_STYLE = r"""
* {
    font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif;
    font-size: 10.5pt;
}
QMainWindow, QDialog {
    background-color: #f4f1ea;
    color: #10263f;
}
QWidget {
    color: #10263f;
}
QLabel {
    color: #34495e;
    background-color: transparent;
}
QLabel#brandTitle {
    color: #0a2747;
    font-size: 19pt;
    font-weight: 700;
}
QLabel#eyebrowLabel {
    color: #5d6c7b;
    font-size: 8.5pt;
    font-weight: 700;
    letter-spacing: 1.2px;
}
QLabel#pageHeading, QLabel#tutorialHeading {
    color: #10263f;
    font-size: 20pt;
    font-weight: 700;
}
QLabel#tutorialStepTitle, QLabel#inspectorTitle {
    color: #10263f;
    font-size: 15pt;
    font-weight: 700;
}
QLabel#inspectorMeta {
    color: #445a70;
    line-height: 1.35;
}
QLabel#tutorialCopy {
    color: #53677a;
    font-size: 11.5pt;
}
QLabel#advancedNotice {
    background-color: #e8f0f5;
    border: 1px solid #aabcca;
    border-radius: 7px;
    padding: 10px;
}
QFrame#appHeader {
    background-color: #faf8f3;
    border: 1px solid #d3d8dc;
    border-radius: 10px;
}
QFrame#commandBar, QFrame#filterBar {
    background-color: #fbfaf7;
    border: 1px solid #d5dadd;
    border-radius: 8px;
}
QFrame#resourcePanel, QFrame#inspectorPanel {
    background-color: #f8f6f1;
    border: 1px solid #ccd4da;
}
QFrame#inspectorMetaCard, QFrame#validationCard {
    background-color: #fcfbf8;
    border: 1px solid #d4d9dd;
    border-radius: 8px;
}
QWidget#scheduleCanvas {
    background-color: #fcfbf8;
}
QFrame#runStrip {
    background-color: #0b2b4d;
    border: 1px solid #0b2b4d;
    border-radius: 7px;
}
QFrame#runStrip QLabel {
    color: #f8fafc;
}
QSplitter::handle {
    background-color: #ccd4da;
    width: 1px;
}
QTabWidget#workspaceTabs::pane {
    border: 1px solid #ccd4da;
    background-color: #fcfbf8;
}
QTabBar::tab {
    background-color: #eceff1;
    color: #334b62;
    border: 1px solid #ccd4da;
    border-bottom: 0;
    padding: 8px 19px;
    min-width: 82px;
}
QTabBar::tab:selected {
    background-color: #0d3b66;
    color: #ffffff;
}
QTabBar::tab:hover:!selected {
    background-color: #e0e9ef;
    color: #153b5e;
}
QGroupBox {
    background-color: #fcfbf8;
    border: 1px solid #ccd4da;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 11px;
    font-weight: 700;
    color: #18344f;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}
QComboBox, QSpinBox, QLineEdit, QPlainTextEdit {
    background-color: #fffefa;
    color: #142b43;
    border: 1px solid #a9b6c1;
    border-radius: 7px;
    padding: 7px 9px;
    selection-background-color: #1c5d8f;
    selection-color: #ffffff;
}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover,
QComboBox:focus, QSpinBox:focus, QLineEdit:focus,
QPlainTextEdit:focus {
    border-color: #1c5d8f;
}
QComboBox::drop-down {
    border: 0;
    width: 22px;
}
QComboBox QAbstractItemView {
    background-color: #fffefa;
    color: #142b43;
    border: 1px solid #a9b6c1;
    selection-background-color: #dbe9f3;
    selection-color: #10263f;
}
QPushButton, QToolButton {
    color: #ffffff;
    background-color: #1f6599;
    border: 1px solid #1f6599;
    border-radius: 7px;
    padding: 8px 14px;
    font-weight: 600;
}
QPushButton:hover, QToolButton:hover {
    background-color: #164c75;
    border-color: #164c75;
}
QPushButton:pressed, QToolButton:pressed {
    background-color: #103a59;
}
QPushButton:focus, QToolButton:focus {
    border: 2px solid #0b2b4d;
}
QPushButton:disabled, QToolButton:disabled {
    color: #687b8e;
    background-color: #e3e8eb;
    border-color: #ccd4da;
}
QPushButton#quietButton, QToolButton#quietButton {
    color: #18344f;
    background-color: transparent;
    border-color: #a9b6c1;
}
QPushButton#quietButton:hover, QToolButton#quietButton:hover {
    background-color: #e8edf0;
}
QPushButton#secondaryButton, QToolButton#secondaryButton {
    color: #1b5d90;
    background-color: #fffefa;
    border-color: #1b5d90;
}
QPushButton#publishButton {
    color: #ffffff;
    background-color: #176b4c;
    border-color: #176b4c;
}
QPushButton#publishButton:hover {
    background-color: #105239;
    border-color: #105239;
}
QToolButton[spinStep="true"] {
    color: #173654;
    background-color: #eee8de;
    border: 1px solid #aa9e8b;
    padding: 0;
    min-width: 18px;
    font-weight: 700;
}
QMenu {
    background-color: #fffefa;
    color: #142b43;
    border: 1px solid #a9b6c1;
}
QMenu::item { padding: 8px 25px; }
QMenu::item:selected { background-color: #dbe9f3; color: #10263f; }
QListWidget#resourceList {
    background-color: transparent;
    color: #334b62;
    border: 0;
    outline: 0;
}
QListWidget#resourceList::item {
    padding: 7px 6px;
    border-bottom: 1px solid #e1e5e7;
}
QListWidget#resourceList::item:selected {
    background-color: #dbe9f3;
    color: #153b5e;
    border-left: 3px solid #1c5d8f;
}
QTableWidget, QTableView {
    background-color: #fffefa;
    alternate-background-color: #f7f5ef;
    color: #17324d;
    gridline-color: #ced7df;
    border: 1px solid #c5d0d9;
    selection-background-color: transparent;
    selection-color: #17324d;
}
QTableWidget::item, QTableView::item {
    padding: 6px;
}
QTableWidget::item:selected {
    border: 2px solid #174e77;
}
QHeaderView::section {
    background-color: #f2f3f1;
    color: #213b55;
    border: 0;
    border-right: 1px solid #ced7df;
    border-bottom: 1px solid #b6c3ce;
    padding: 8px;
    font-weight: 700;
}
QScrollArea, QAbstractScrollArea {
    background-color: transparent;
    border: 0;
}
QScrollBar:vertical {
    background-color: #edf0f2;
    border: 0;
    width: 10px;
    margin: 0;
}
QScrollBar:horizontal {
    background-color: #edf0f2;
    border: 0;
    height: 10px;
    margin: 0;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background-color: #8ea0af;
    border-radius: 5px;
    min-height: 32px;
    min-width: 32px;
}
QScrollBar::handle:hover { background-color: #6f8496; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QFrame#statusToast {
    background-color: #edf4f8;
    border: 1px solid #8fa9ba;
    border-left: 4px solid #1d5f8e;
    border-radius: 8px;
}
QFrame#statusToast[level="busy"] { background-color: #eef4f8; border-left-color: #1f6599; }
QFrame#statusToast[level="success"] { background-color: #edf7f1; border-color: #9bbfa9; border-left-color: #176b4c; }
QFrame#statusToast[level="warning"] { background-color: #fff6df; border-color: #c9aa61; border-left-color: #986b0d; }
QFrame#statusToast[level="error"] { background-color: #fbefef; border-color: #ce9999; border-left-color: #a83f3f; }
QFrame#statusToast QLabel#toastMessage { color: #18344f; font-weight: 600; }
QToolButton#toastCloseButton {
    background-color: transparent;
    border: 0;
    padding: 3px;
}
QToolButton#toastCloseButton:hover { background-color: #dce5eb; }
QProgressBar#toastProgress { background-color: #d5e2ea; border: 0; border-radius: 1px; }
QProgressBar#toastProgress::chunk { background-color: #1f6599; }
QToolTip {
    color: #ffffff;
    background-color: #10263f;
    border: 1px solid #40566c;
    padding: 6px;
}
QDialog#tutorialDialog {
    background-color: #fffefa;
    border: 1px solid #a9b6c1;
}
/* Retained compatibility token for existing theme assertions: #eef2f7 */
"""


DARK_STYLE = r"""
* {
    font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif;
    font-size: 10.5pt;
}
QMainWindow, QDialog {
    background-color: #08111f;
    color: #f3f7fc;
}
QWidget {
    color: #f3f7fc;
}
QLabel {
    color: #d7e1ec;
    background-color: transparent;
}
QLabel#brandTitle, QLabel#pageHeading, QLabel#tutorialHeading,
QLabel#tutorialStepTitle, QLabel#inspectorTitle {
    color: #f7f9fc;
    font-weight: 700;
}
QLabel#brandTitle { font-size: 19pt; }
QLabel#pageHeading, QLabel#tutorialHeading { font-size: 20pt; }
QLabel#tutorialStepTitle, QLabel#inspectorTitle { font-size: 15pt; }
QLabel#eyebrowLabel {
    color: #aebfd0;
    font-size: 8.5pt;
    font-weight: 700;
    letter-spacing: 1.2px;
}
QLabel#inspectorMeta, QLabel#tutorialCopy { color: #c3d0dc; }
QLabel#tutorialCopy { font-size: 11.5pt; }
QLabel#advancedNotice {
    background-color: #17334d;
    color: #f1f6fb;
    border: 1px solid #496b8b;
    border-radius: 7px;
    padding: 10px;
}
QFrame#appHeader {
    background-color: #0a1626;
    border: 1px solid #32485e;
    border-radius: 10px;
}
QFrame#commandBar, QFrame#filterBar {
    background-color: #0d1a2a;
    border: 1px solid #334a62;
    border-radius: 8px;
}
QFrame#resourcePanel, QFrame#inspectorPanel {
    background-color: #0f1d2d;
    border: 1px solid #334a62;
}
QFrame#inspectorMetaCard, QFrame#validationCard {
    background-color: #122235;
    border: 1px solid #3a5068;
    border-radius: 8px;
}
QWidget#scheduleCanvas { background-color: #0b1725; }
QFrame#runStrip {
    background-color: #071d36;
    border: 1px solid #334a62;
    border-radius: 7px;
}
QFrame#runStrip QLabel { color: #f7fbff; }
QSplitter::handle { background-color: #334a62; width: 1px; }
QTabWidget#workspaceTabs::pane {
    border: 1px solid #334a62;
    background-color: #0b1725;
}
QTabBar::tab {
    background-color: #132337;
    color: #d4dfeb;
    border: 1px solid #334a62;
    border-bottom: 0;
    padding: 8px 19px;
    min-width: 82px;
}
QTabBar::tab:selected { background-color: #174d78; color: #ffffff; }
QTabBar::tab:hover:!selected { background-color: #1b3048; color: #ffffff; }
QGroupBox {
    background-color: #122235;
    border: 1px solid #3a5068;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 11px;
    font-weight: 700;
    color: #f3f7fc;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; }
QComboBox, QSpinBox, QLineEdit, QPlainTextEdit {
    background-color: #132337;
    color: #f3f7fc;
    border: 1px solid #5d7188;
    border-radius: 7px;
    padding: 7px 9px;
    selection-background-color: #3978b8;
    selection-color: #ffffff;
}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover,
QComboBox:focus, QSpinBox:focus, QLineEdit:focus,
QPlainTextEdit:focus { border-color: #8ab9e6; }
QComboBox::drop-down { border: 0; width: 22px; }
QComboBox QAbstractItemView {
    background-color: #132337;
    color: #f3f7fc;
    border: 1px solid #5d7188;
    selection-background-color: #1f5684;
}
QPushButton, QToolButton {
    color: #ffffff;
    background-color: #26689f;
    border: 1px solid #77a9d6;
    border-radius: 7px;
    padding: 8px 14px;
    font-weight: 600;
}
QPushButton:hover, QToolButton:hover { background-color: #347db8; border-color: #a4caec; }
QPushButton:pressed, QToolButton:pressed { background-color: #174b78; }
QPushButton:focus, QToolButton:focus { border: 2px solid #b6d7f4; }
QPushButton:disabled, QToolButton:disabled {
    color: #8ca0b6;
    background-color: #15253a;
    border-color: #334a62;
}
QPushButton#quietButton, QToolButton#quietButton {
    color: #e6eef7;
    background-color: transparent;
    border-color: #5d7188;
}
QPushButton#quietButton:hover, QToolButton#quietButton:hover { background-color: #182b41; }
QPushButton#secondaryButton, QToolButton#secondaryButton {
    color: #e1effc;
    background-color: #122235;
    border-color: #77a9d6;
}
QPushButton#publishButton { background-color: #28785d; border-color: #65bf98; }
QPushButton#publishButton:hover { background-color: #329271; border-color: #8bd8b8; }
QToolButton[spinStep="true"] {
    color: #f3f7fc;
    background-color: #1b3048;
    border: 1px solid #5d7188;
    padding: 0;
    min-width: 18px;
    font-weight: 700;
}
QMenu { background-color: #122235; color: #f3f7fc; border: 1px solid #5d7188; }
QMenu::item { padding: 8px 25px; }
QMenu::item:selected { background-color: #1f5684; }
QListWidget#resourceList {
    background-color: transparent;
    color: #d4dfeb;
    border: 0;
    outline: 0;
}
QListWidget#resourceList::item {
    padding: 7px 6px;
    border-bottom: 1px solid #293d53;
}
QListWidget#resourceList::item:selected {
    background-color: #1b3048;
    color: #ffffff;
    border-left: 3px solid #78aee6;
}
QTableWidget, QTableView {
    background-color: #0d1a2a;
    alternate-background-color: #122235;
    color: #f3f7fc;
    gridline-color: #334a62;
    border: 1px solid #334a62;
    selection-background-color: transparent;
    selection-color: #17324d;
}
QTableWidget::item, QTableView::item { padding: 6px; }
QTableWidget::item:selected { border: 2px solid #a9d3f5; }
QHeaderView::section {
    background-color: #132337;
    color: #d8e3ee;
    border: 0;
    border-right: 1px solid #334a62;
    border-bottom: 1px solid #5d7188;
    padding: 8px;
    font-weight: 700;
}
QScrollArea, QAbstractScrollArea { background-color: transparent; border: 0; }
QScrollArea > QWidget > QWidget { background-color: transparent; }
QScrollBar:vertical {
    background-color: #132337;
    border: 0;
    width: 10px;
    margin: 0;
}
QScrollBar:horizontal {
    background-color: #132337;
    border: 0;
    height: 10px;
    margin: 0;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background-color: #60758c;
    border-radius: 5px;
    min-height: 32px;
    min-width: 32px;
}
QScrollBar::handle:hover { background-color: #8095aa; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QFrame#statusToast {
    background-color: #12283c;
    border: 1px solid #496b8b;
    border-left: 4px solid #6da8d6;
    border-radius: 8px;
}
QFrame#statusToast[level="busy"] { background-color: #12283c; border-left-color: #78aee6; }
QFrame#statusToast[level="success"] { background-color: #112d26; border-color: #3f8067; border-left-color: #67c79d; }
QFrame#statusToast[level="warning"] { background-color: #342a13; border-color: #806a38; border-left-color: #ddb85f; }
QFrame#statusToast[level="error"] { background-color: #351b22; border-color: #824d58; border-left-color: #ef8f9f; }
QFrame#statusToast QLabel#toastMessage { color: #f3f7fc; font-weight: 600; }
QToolButton#toastCloseButton { background-color: transparent; border: 0; padding: 3px; }
QToolButton#toastCloseButton:hover { background-color: #263b52; }
QProgressBar#toastProgress { background-color: #263b52; border: 0; border-radius: 1px; }
QProgressBar#toastProgress::chunk { background-color: #78aee6; }
QToolTip {
    color: #08111f;
    background-color: #e7edf4;
    border: 1px solid #92a4b6;
    padding: 6px;
}
QDialog#tutorialDialog { background-color: #0f1d2d; border: 1px solid #5d7188; }
"""
