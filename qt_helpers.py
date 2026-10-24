from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QPushButton,QLineEdit,QCheckBox,QComboBox,QProgressBar,QMessageBox,QFileDialog
from i18n import tr as t

class Var(QObject):
    changed=Signal(object)
    def __init__(self,value=''):super().__init__();self.value=value
    def get(self):return self.value
    def set(self,value):
        if value!=self.value:self.value=value;self.changed.emit(value)
    def bind(self,widget):
        if isinstance(widget,QLineEdit):widget.setText(self.value);self.changed.connect(widget.setText);widget.textChanged.connect(self.set)
        elif isinstance(widget,QCheckBox):widget.setChecked(bool(self.value));self.changed.connect(widget.setChecked);widget.toggled.connect(self.set)
        elif isinstance(widget,Combo):self.changed.connect(widget.apply_choice)
        else:widget.setText(str(self.value));self.changed.connect(widget.setText)
        return widget

class Configurable:
    def configure(self,**values):
        if 'state'in values:self.setEnabled(values['state']!='disabled')
        if 'text'in values:self.setText(values['text'])
        if 'value'in values:self.setValue(round(values['value']))
        if 'values'in values:self.clear();self.addItems(values['values'])

class Button(QPushButton,Configurable):
    def __init__(self,text,action=None,primary=False):
        super().__init__(text);self.setCursor(__import__('PySide6.QtCore',fromlist=['Qt']).Qt.PointingHandCursor)
        if action:self.clicked.connect(action)
        if primary:self.setObjectName('primary')
class Entry(QLineEdit,Configurable):pass
class Check(QCheckBox,Configurable):pass
class Progress(QProgressBar,Configurable):
    def __init__(self):super().__init__();self.setRange(0,100);self.setTextVisible(False);self.setFixedHeight(5)
class Combo(QComboBox,Configurable):
    def current(self,index=None):
        if index is None:return self.currentIndex()
        self.setCurrentIndex(index)
    @Slot(object)
    def apply_choice(self,value):self.setCurrentIndex(self.findText(value)if value else-1)

class MessageBox:
    def showinfo(self,title,text,parent=None):
        box=QMessageBox(parent);box.setWindowTitle(title);box.setText(text);box.setStandardButtons(QMessageBox.Ok);box.button(QMessageBox.Ok).setText(t('确定'));box.exec()
    def showerror(self,title,text,parent=None):
        box=QMessageBox(parent);box.setWindowTitle(title);box.setIcon(QMessageBox.Warning);box.setText(text);box.setStandardButtons(QMessageBox.Ok);box.button(QMessageBox.Ok).setText(t('确定'));box.exec()
    def askyesno(self,title,text,parent=None,default='no'):
        box=QMessageBox(parent);box.setWindowTitle(title);box.setText(text);box.setStandardButtons(QMessageBox.Yes|QMessageBox.No)
        box.button(QMessageBox.Yes).setText(t('继续'));box.button(QMessageBox.No).setText(t('取消'));box.setDefaultButton(QMessageBox.No)
        return box.exec()==QMessageBox.Yes
messagebox=MessageBox()
class FileDialog:
    def askopenfilename(self,parent=None,title='',filetypes=None):return QFileDialog.getOpenFileName(parent,title,'','IPA (*.ipa)')[0]
filedialog=FileDialog()
