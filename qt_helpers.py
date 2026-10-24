from PySide6.QtCore import QObject, Signal, Slot,Qt,QSize,QRectF
from PySide6.QtGui import QAction,QIcon,QPixmap,QPainter,QColor
from PySide6.QtSvg import QSvgRenderer
from functools import lru_cache
from PySide6.QtWidgets import QPushButton,QLineEdit,QCheckBox,QComboBox,QProgressBar,QMessageBox,QFileDialog
from i18n import tr as t

def add_visibility_toggle(entry,code=False):
    from security import BUNDLE
    entry.setEchoMode(QLineEdit.Password)
    action=QAction(entry);action.setCheckable(True)
    def update(shown):
        entry.setEchoMode(QLineEdit.Normal if shown else QLineEdit.Password)
        text=(t('隐藏验证码')if shown else t('显示验证码'))if code else(t('隐藏密码')if shown else t('显示密码'))
        action.setText(text);action.setToolTip(text)
        action.setIcon(QIcon(str(BUNDLE/'assets'/('eye-off.svg'if shown else'eye.svg'))))
    action.toggled.connect(update);update(False);entry.addAction(action,QLineEdit.TrailingPosition)
    return action

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
    def __init__(self,text,action=None,primary=False,icon=None):
        super().__init__(text);self.setCursor(__import__('PySide6.QtCore',fromlist=['Qt']).Qt.PointingHandCursor)
        if action:self.clicked.connect(action)
        if primary:self.setObjectName('primary')
        if icon:self.setIcon(button_icon(icon,primary));self.setIconSize(QSize(18,18))

@lru_cache(maxsize=40)
def button_icon(name,primary=False):
    from security import BUNDLE
    renderer=QSvgRenderer(str(BUNDLE/'assets/fontawesome'/(name+'.svg')))
    if not renderer.isValid():raise ValueError('Missing interface icon')
    icon=QIcon();source=renderer.defaultSize()
    for size in (18,24,36,48,64):
        for mode,color in ((QIcon.Normal,'#152019'if primary else'#d3dfc8'),(QIcon.Disabled,'#788570')):
            pixmap=QPixmap(size,size);pixmap.fill(Qt.transparent);painter=QPainter(pixmap)
            scale=(size-2)/max(source.width(),source.height());w=source.width()*scale;h=source.height()*scale
            renderer.render(painter,QRectF((size-w)/2,(size-h)/2,w,h))
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn);painter.fillRect(pixmap.rect(),QColor(color));painter.end()
            icon.addPixmap(pixmap,mode)
    return icon
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
