from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QTableWidget,QTableWidgetItem,QAbstractItemView
from qt_helpers import Button,Entry,messagebox,add_visibility_toggle
from i18n import tr as t
import re

class AuthDialogs:
    def dismiss_dialog(self):
        if self.dialog:
            dialog=self.dialog;self.dialog=None;dialog._answered=True;dialog.close();dialog.deleteLater()
    def new_dialog(self,title,cancel):
        self.dismiss_dialog();dialog=QDialog(self);dialog.setWindowTitle(title);dialog.setMinimumWidth(450);dialog.setModal(True);dialog._answered=False
        layout=QVBoxLayout(dialog);layout.setContentsMargins(25,23,25,23);layout.setSpacing(14)
        def rejected():
            if not dialog._answered:dialog._answered=True;cancel()
        dialog.rejected.connect(rejected);self.dialog=dialog;return dialog,layout
    def answer(self,value):self.send(value);self.dismiss_dialog()
    def code_dialog(self,data):
        d,box=self.new_dialog(t('Apple 双重认证'),lambda:self.answer({'value':'q'}))
        label=QLabel(t('请输入手机收到的六位验证码。\n验证码仅提交给 Apple，不保存。'));label.setWordWrap(True);box.addWidget(label)
        entry=Entry();add_visibility_toggle(entry,code=True);entry.setMaxLength(6);entry.setPlaceholderText('000000');box.addWidget(entry);d.finished.connect(entry.clear)
        def submit():
            value=entry.text().strip()
            if not re.fullmatch('[0-9]{6}',value):messagebox.showerror('RhineSign',t('请输入六位数字。'),parent=d);return
            entry.clear();self.answer({'value':value})
        box.addWidget(Button(t('提交验证码'),submit,True));entry.returnPressed.connect(submit)
        box.addWidget(Button(t('发送到受信任设备'),lambda:self.answer({'value':'d'})))
        for n in data.get('numbers',[]):box.addWidget(Button(t('短信验证 · 尾号 ')+str(n['tail']),lambda checked=False,i=n['id']:self.answer({'value':'p'+str(i)})))
        box.addWidget(Button(t('取消认证'),lambda:self.answer({'value':'q'})));d.show();entry.setFocus()
    def team_dialog(self,data):
        d,box=self.new_dialog(t('选择开发者团队'),self.cancel);box.addWidget(QLabel(t('选择用于本次个人签名的团队：')))
        for team in data:box.addWidget(Button(str(team['name'])+' / '+str(team['id']),lambda checked=False,i=team['index']:self.answer({'index':i})))
        d.show()
    def certificates_dialog(self,data):
        d,box=self.new_dialog(t('个人签名资格已满 · 7460'),lambda:self.answer({'action':'cancel'}));d.resize(830,410)
        label=QLabel(t('请选择一张确认不再需要的旧证书。撤销后，依赖它的其他自签 App 可能需要重新签名。\n原版 App Store 下载的 App 不使用这些个人开发证书。默认不选中、不撤销。'));label.setWordWrap(True);box.addWidget(label)
        table=QTableWidget(len(data),4);table.setHorizontalHeaderLabels([t(x)for x in('证书名称','来源／机器','有效期','序列号末 8 位')]);table.setSelectionBehavior(QAbstractItemView.SelectRows);table.setSelectionMode(QAbstractItemView.SingleSelection);table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        for row,c in enumerate(data):
            for col,value in enumerate([c.get('name')or t('未命名'),c.get('machine')or t('未知'),c.get('expires')or t('未知'),str(c.get('serial',''))[-8:]]):table.setItem(row,col,QTableWidgetItem(str(value)))
        table.resizeColumnsToContents();table.clearSelection();table.setCurrentCell(-1,-1);box.addWidget(table)
        def replace():
            selected=table.selectionModel().selectedRows()
            if len(selected)!=1:messagebox.showinfo('RhineSign',t('请先选择你确认不再需要的一张旧证书；不确定时请取消。'),parent=d);return
            c=data[selected[0].row()];details=t('名称：')+str(c.get('name',''))+t('\n来源：')+str(c.get('machine',''))+t('\n序列号：')+str(c['serial'])
            warning=t('\n\n依赖这张证书的其他自签 App 可能无法继续运行，需要重新签名。\n撤销无法撤回，之后申请新的个人签名资格也可能因其他限制失败。\n\n确定撤销这张证书并继续？')
            if messagebox.askyesno(t('确认撤销这张旧证书？'),details+warning,parent=d,default='no'):self.answer({'confirmed':True,'serial':c['serial']})
        row=QHBoxLayout();row.addWidget(Button(t('取消，不更改任何证书'),lambda:self.answer({'action':'cancel'})));row.addStretch();row.addWidget(Button(t('选择的旧证书 → 确认替换…'),replace,True));box.addLayout(row);d.show()
