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
    border: 1px solid #555555;
    border-radius: 3px;
    padding: 2px 6px;
}
QComboBox:hover, QSpinBox:hover {
    background-color: #26262b;
}
QSpinBox::up-button, QSpinBox::down-button {
    background-color: #4b2e83;
    border: none;
    width: 18px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background-color: #6a44c2;
}
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {
    background-color: #38215c;
}

QPushButton {
    color: #ffffff;
    background-color: #4b2e83;
    border-radius: 4px;
    padding: 4px 10px;
}
QPushButton:hover {
    background-color: #6a44c2;
}
QPushButton:pressed {
    background-color: #38215c;
}
QPushButton:disabled {
    background-color: #555555;
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
