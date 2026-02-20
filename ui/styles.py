DARK_STYLE = """
QMainWindow {
    background-color: #121212;
}
QLabel {
    color: #f5f5f5;
    font-size: 10pt;
}
QComboBox, QPushButton, QSpinBox {
    font-size: 10pt;
}
QComboBox, QSpinBox {
    background-color: #1f1f23;
    color: #f5f5f5;
    border: 2px solid #6d727a;
    border-radius: 3px;
}
QComboBox {
    padding: 2px 6px;
}
QSpinBox {
    padding: 2px 22px 2px 22px;
}
QSpinBox[stepBox="true"] {
    border: 2px solid #8a9099;
    padding: 2px 20px 2px 20px;
}
QSpinBox[stepBox="true"]:hover {
    border-color: #a2a9b3;
}
QSpinBox[stepBox="true"]:focus {
    border-color: #9eb8ff;
}
QComboBox:hover, QSpinBox:hover {
    background-color: #26262b;
    border: 2px solid #8a9099;
}
QComboBox:focus, QSpinBox:focus {
    border: 2px solid #9eb8ff;
}
QToolButton[spinStep="true"] {
    color: #f5f5f5;
    background-color: #26262b;
    border: 2px solid #8a9099;
    padding: 0px;
    margin: 0px;
    min-width: 18px;
    font-weight: bold;
    font-size: 10pt;
}
QToolButton[spinStep="true"][spinDir="left"] {
    border-top-left-radius: 3px;
    border-bottom-left-radius: 3px;
}
QToolButton[spinStep="true"][spinDir="right"] {
    border-top-right-radius: 3px;
    border-bottom-right-radius: 3px;
    border-right: 2px solid #b8c0cb;
}
QToolButton[spinStep="true"]:hover {
    background-color: #33353b;
    border-color: #a2a9b3;
}
QToolButton[spinStep="true"]:pressed {
    background-color: #1a1c20;
    border-color: #b6bec9;
}
QToolButton[spinStep="true"][spinDir="right"]:hover {
    border-right-color: #c6ceda;
}
QToolButton[spinStep="true"][spinDir="right"]:pressed {
    border-right-color: #d2d9e3;
}

QPushButton {
    color: #ffffff;
    background-color: #4b2e83;
    border: 2px solid #8f83a7;
    border-radius: 4px;
    padding: 4px 10px;
}
QPushButton:hover {
    background-color: #6a44c2;
    border-color: #b7a9d5;
}
QPushButton:pressed {
    background-color: #38215c;
    border-color: #9f93bc;
}
QPushButton:disabled {
    background-color: #555555;
    border-color: #6b6b6b;
}
QToolButton {
    color: #f5f5f5;
    background-color: #26262b;
    border: 2px solid #7d838b;
    border-radius: 4px;
    padding: 3px 8px;
}
QToolButton:hover {
    border-color: #a6adb7;
}
QToolButton:pressed {
    border-color: #b8c0cb;
}
QToolButton:disabled {
    border-color: #666a70;
}
QTableWidget {
    background-color: #18181c;
    color: #f5f5f5;
    gridline-color: #3c3f41;
    font-size: 9pt;
}
QTableWidget::item:selected {
    background-color: #3c78d8;
    color: #ffffff;
}
QHeaderView::section {
    background-color: #26262b;
    color: #f5f5f5;
    font-weight: bold;
}
"""
