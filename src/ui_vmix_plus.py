# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'vmix_plus.ui'
##
## Created by: Qt User Interface Compiler version 6.12.0
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import *  # type: ignore
from PySide6.QtGui import *  # type: ignore
from PySide6.QtWidgets import *  # type: ignore

class Ui_VMixPlusPage(object):
    def setupUi(self, VMixPlusPage):
        if not VMixPlusPage.objectName():
            VMixPlusPage.setObjectName(u"VMixPlusPage")
        self.verticalLayout = QVBoxLayout(VMixPlusPage)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.label_intro = QLabel(VMixPlusPage)
        self.label_intro.setObjectName(u"label_intro")
        self.label_intro.setWordWrap(True)

        self.verticalLayout.addWidget(self.label_intro)

        self.connectionLayout = QHBoxLayout()
        self.connectionLayout.setObjectName(u"connectionLayout")
        self.label_connection = QLabel(VMixPlusPage)
        self.label_connection.setObjectName(u"label_connection")

        self.connectionLayout.addWidget(self.label_connection)

        self.lineEdit_host = QLineEdit(VMixPlusPage)
        self.lineEdit_host.setObjectName(u"lineEdit_host")

        self.connectionLayout.addWidget(self.lineEdit_host)

        self.label_separator = QLabel(VMixPlusPage)
        self.label_separator.setObjectName(u"label_separator")
        self.label_separator.setText(u":")

        self.connectionLayout.addWidget(self.label_separator)

        self.lineEdit_port = QLineEdit(VMixPlusPage)
        self.lineEdit_port.setObjectName(u"lineEdit_port")
        self.lineEdit_port.setMaximumSize(QSize(70, 16777215))

        self.connectionLayout.addWidget(self.lineEdit_port)

        self.pushButton_start = QPushButton(VMixPlusPage)
        self.pushButton_start.setObjectName(u"pushButton_start")
        self.pushButton_start.setCheckable(True)

        self.connectionLayout.addWidget(self.pushButton_start)


        self.verticalLayout.addLayout(self.connectionLayout)

        self.discoveryLayout = QHBoxLayout()
        self.discoveryLayout.setObjectName(u"discoveryLayout")
        self.pushButton_fetch = QPushButton(VMixPlusPage)
        self.pushButton_fetch.setObjectName(u"pushButton_fetch")

        self.discoveryLayout.addWidget(self.pushButton_fetch)

        self.label_fields = QLabel(VMixPlusPage)
        self.label_fields.setObjectName(u"label_fields")
        self.label_fields.setWordWrap(True)
        self.label_fields.setTextFormat(Qt.PlainText)

        self.discoveryLayout.addWidget(self.label_fields)


        self.verticalLayout.addLayout(self.discoveryLayout)

        self.label_transport = QLabel(VMixPlusPage)
        self.label_transport.setObjectName(u"label_transport")
        self.label_transport.setWordWrap(True)

        self.verticalLayout.addWidget(self.label_transport)

        self.checkBox_sendSame = QCheckBox(VMixPlusPage)
        self.checkBox_sendSame.setObjectName(u"checkBox_sendSame")

        self.verticalLayout.addWidget(self.checkBox_sendSame)

        self.tableView_mapping = QTableView(VMixPlusPage)
        self.tableView_mapping.setObjectName(u"tableView_mapping")
        self.tableView_mapping.setAlternatingRowColors(True)

        self.verticalLayout.addWidget(self.tableView_mapping)

#if QT_CONFIG(shortcut)
        self.label_connection.setBuddy(self.lineEdit_host)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(VMixPlusPage)

        QMetaObject.connectSlotsByName(VMixPlusPage)
    # setupUi

    def retranslateUi(self, VMixPlusPage):
        self.label_intro.setText(QCoreApplication.translate("VMixPlusPage", u"Update every vMix title with matching field names, including titles that are off air.", None))
        self.label_connection.setText(QCoreApplication.translate("VMixPlusPage", u"Connection", None))
        self.lineEdit_host.setPlaceholderText(QCoreApplication.translate("VMixPlusPage", u"localhost", None))
#if QT_CONFIG(accessibility)
        self.lineEdit_port.setAccessibleName(QCoreApplication.translate("VMixPlusPage", u"Web API port", None))
#endif // QT_CONFIG(accessibility)
#if QT_CONFIG(tooltip)
        self.lineEdit_port.setToolTip(QCoreApplication.translate("VMixPlusPage", u"Web API port for finding fields. Live values use the fixed TCP port 8099.", None))
#endif // QT_CONFIG(tooltip)
        self.pushButton_start.setText(QCoreApplication.translate("VMixPlusPage", u"Start vMix API+", None))
        self.pushButton_fetch.setText(QCoreApplication.translate("VMixPlusPage", u"Fetch fields", None))
#if QT_CONFIG(tooltip)
        self.pushButton_fetch.setToolTip(QCoreApplication.translate("VMixPlusPage", u"Find text fields in all vMix inputs. Fields are also refreshed every five seconds while this output is on.", None))
#endif // QT_CONFIG(tooltip)
        self.label_fields.setText("")
        self.label_transport.setText(QCoreApplication.translate("VMixPlusPage", u"Fields: HTTP port above. Live updates: TCP 8099.", None))
        self.checkBox_sendSame.setText(QCoreApplication.translate("VMixPlusPage", u"Also resend unchanged values", None))
#if QT_CONFIG(tooltip)
        self.tableView_mapping.setToolTip(QCoreApplication.translate("VMixPlusPage", u"Choose an exact vMix text-field name, including .Text for GT titles. Every matching title receives the value. Clear a mapping to stop sending it.", None))
#endif // QT_CONFIG(tooltip)
        pass
    # retranslateUi

