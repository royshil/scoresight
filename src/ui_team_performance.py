# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'team_performance.ui'
##
## Created by: Qt User Interface Compiler version 6.12.0
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import *  # type: ignore
from PySide6.QtGui import *  # type: ignore
from PySide6.QtWidgets import *  # type: ignore

class Ui_TeamPerformancePage(object):
    def setupUi(self, TeamPerformancePage):
        if not TeamPerformancePage.objectName():
            TeamPerformancePage.setObjectName(u"TeamPerformancePage")
        self.verticalLayout = QVBoxLayout(TeamPerformancePage)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.checkBox_enabled = QCheckBox(TeamPerformancePage)
        self.checkBox_enabled.setObjectName(u"checkBox_enabled")

        self.verticalLayout.addWidget(self.checkBox_enabled)

        self.label_intro = QLabel(TeamPerformancePage)
        self.label_intro.setObjectName(u"label_intro")
        self.label_intro.setWordWrap(True)

        self.verticalLayout.addWidget(self.label_intro)

        self.formLayout = QFormLayout()
        self.formLayout.setObjectName(u"formLayout")
        self.label_scoreboardField = QLabel(TeamPerformancePage)
        self.label_scoreboardField.setObjectName(u"label_scoreboardField")

        self.formLayout.setWidget(0, QFormLayout.ItemRole.LabelRole, self.label_scoreboardField)

        self.comboBox_scoreboardField = QComboBox(TeamPerformancePage)
        self.comboBox_scoreboardField.setObjectName(u"comboBox_scoreboardField")

        self.formLayout.setWidget(0, QFormLayout.ItemRole.FieldRole, self.comboBox_scoreboardField)

        self.label_shotClockField = QLabel(TeamPerformancePage)
        self.label_shotClockField.setObjectName(u"label_shotClockField")

        self.formLayout.setWidget(1, QFormLayout.ItemRole.LabelRole, self.label_shotClockField)

        self.comboBox_shotClockField = QComboBox(TeamPerformancePage)
        self.comboBox_shotClockField.setObjectName(u"comboBox_shotClockField")

        self.formLayout.setWidget(1, QFormLayout.ItemRole.FieldRole, self.comboBox_shotClockField)


        self.verticalLayout.addLayout(self.formLayout)

        self.label_urls = QLabel(TeamPerformancePage)
        self.label_urls.setObjectName(u"label_urls")
        self.label_urls.setWordWrap(True)

        self.verticalLayout.addWidget(self.label_urls)

        self.urlLayout = QFormLayout()
        self.urlLayout.setObjectName(u"urlLayout")
        self.label_scoreboardUrl = QLabel(TeamPerformancePage)
        self.label_scoreboardUrl.setObjectName(u"label_scoreboardUrl")

        self.urlLayout.setWidget(0, QFormLayout.ItemRole.LabelRole, self.label_scoreboardUrl)

        self.scoreboardUrlLayout = QHBoxLayout()
        self.scoreboardUrlLayout.setObjectName(u"scoreboardUrlLayout")
        self.lineEdit_scoreboardUrl = QLineEdit(TeamPerformancePage)
        self.lineEdit_scoreboardUrl.setObjectName(u"lineEdit_scoreboardUrl")
        self.lineEdit_scoreboardUrl.setReadOnly(True)

        self.scoreboardUrlLayout.addWidget(self.lineEdit_scoreboardUrl)

        self.pushButton_copyScoreboard = QPushButton(TeamPerformancePage)
        self.pushButton_copyScoreboard.setObjectName(u"pushButton_copyScoreboard")

        self.scoreboardUrlLayout.addWidget(self.pushButton_copyScoreboard)


        self.urlLayout.setLayout(0, QFormLayout.ItemRole.FieldRole, self.scoreboardUrlLayout)

        self.label_shotClockUrl = QLabel(TeamPerformancePage)
        self.label_shotClockUrl.setObjectName(u"label_shotClockUrl")

        self.urlLayout.setWidget(1, QFormLayout.ItemRole.LabelRole, self.label_shotClockUrl)

        self.shotClockUrlLayout = QHBoxLayout()
        self.shotClockUrlLayout.setObjectName(u"shotClockUrlLayout")
        self.lineEdit_shotClockUrl = QLineEdit(TeamPerformancePage)
        self.lineEdit_shotClockUrl.setObjectName(u"lineEdit_shotClockUrl")
        self.lineEdit_shotClockUrl.setReadOnly(True)

        self.shotClockUrlLayout.addWidget(self.lineEdit_shotClockUrl)

        self.pushButton_copyShotClock = QPushButton(TeamPerformancePage)
        self.pushButton_copyShotClock.setObjectName(u"pushButton_copyShotClock")

        self.shotClockUrlLayout.addWidget(self.pushButton_copyShotClock)


        self.urlLayout.setLayout(1, QFormLayout.ItemRole.FieldRole, self.shotClockUrlLayout)


        self.verticalLayout.addLayout(self.urlLayout)

        self.label_preview = QLabel(TeamPerformancePage)
        self.label_preview.setObjectName(u"label_preview")
        self.label_preview.setWordWrap(True)
        self.label_preview.setTextFormat(Qt.PlainText)

        self.verticalLayout.addWidget(self.label_preview)

        self.label_note = QLabel(TeamPerformancePage)
        self.label_note.setObjectName(u"label_note")
        self.label_note.setWordWrap(True)

        self.verticalLayout.addWidget(self.label_note)

        self.verticalSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout.addItem(self.verticalSpacer)

#if QT_CONFIG(shortcut)
        self.label_scoreboardField.setBuddy(self.comboBox_scoreboardField)
        self.label_shotClockField.setBuddy(self.comboBox_shotClockField)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(TeamPerformancePage)

        QMetaObject.connectSlotsByName(TeamPerformancePage)
    # setupUi

    def retranslateUi(self, TeamPerformancePage):
        self.checkBox_enabled.setText(QCoreApplication.translate("TeamPerformancePage", u"Enable Team Performance", None))
        self.label_intro.setText(QCoreApplication.translate("TeamPerformancePage", u"Send the scoreboard time and shot clock to Team Performance without a separate bridge. Select the OCR fields, then copy the URLs into Config. timing devices in Team Performance (scoreboard first, shot clock second).", None))
        self.label_scoreboardField.setText(QCoreApplication.translate("TeamPerformancePage", u"Scoreboard field", None))
        self.label_shotClockField.setText(QCoreApplication.translate("TeamPerformancePage", u"Shot-clock field", None))
        self.label_urls.setText(QCoreApplication.translate("TeamPerformancePage", u"Timing device URLs (use this computer's network address on another computer)", None))
        self.label_scoreboardUrl.setText(QCoreApplication.translate("TeamPerformancePage", u"Scoreboard URL", None))
        self.pushButton_copyScoreboard.setText(QCoreApplication.translate("TeamPerformancePage", u"Copy", None))
        self.label_shotClockUrl.setText(QCoreApplication.translate("TeamPerformancePage", u"Shot-clock URL", None))
        self.pushButton_copyShotClock.setText(QCoreApplication.translate("TeamPerformancePage", u"Copy", None))
        self.label_preview.setText("")
        self.label_note.setText(QCoreApplication.translate("TeamPerformancePage", u"Uses the built-in HTTP server (default port 18099). Times follow the scoreboard, including stops and resets; no countdown is calculated. Match-time tenths are discarded. A missing or invalid clock returns HTTP 503. Temporary failed readings keep the last good value, as with the bridge.", None))
        pass
    # retranslateUi

