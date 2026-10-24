"""RhineSign's Qt desktop workspace."""
import os,queue,sys,webbrowser
from pathlib import Path
from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QIcon,QPixmap,QColor,QPalette,QFont,QFontDatabase
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication,QMainWindow,QWidget,QFrame,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QStackedWidget,QScrollArea,QPlainTextEdit,QSizeGrip,QLineEdit
from qt_helpers import Var,Button,Entry,Check,Progress,Combo,messagebox
from qt_dialogs import AuthDialogs
from operations import Operations,read_settings,PROJECT
from security import BUNDLE,VERSION,remembered_account
from i18n import tr as t,set_language

def label(text='',kind=None):
    item=QLabel(text);item.setWordWrap(True)
    if kind:item.setObjectName(kind)
    return item
def row(*items):
    layout=QHBoxLayout();layout.setSpacing(10)
    for item in items:
        if item is None:layout.addStretch()
        elif isinstance(item,QWidget):layout.addWidget(item)
        else:layout.addLayout(item)
    return layout
def card(title,code):
    frame=QFrame();frame.setObjectName('card');layout=QVBoxLayout(frame);layout.setContentsMargins(16,13,16,13);layout.setSpacing(10)
    layout.addLayout(row(label(t(title),'cardtitle'),None,label(code,'chip')));return frame,layout

class TitleBar(QFrame):
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton and self.window().windowHandle():self.window().windowHandle().startSystemMove()
    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.LeftButton:self.window().toggle_maximize()

class RhineWindow(QMainWindow,Operations,AuthDialogs):
    def __init__(self,preview=False):
        super().__init__();self.root=self;self.preview=preview;self._closed=False
        self.child=None;self.dialog=None;self.aux=None;self.running=False;self.finished=False;self.workspace=None
        self.events=queue.Queue();self.devices=[];self.last_output=None;self.auto_request=None;self.pending_install=None;self.stage='';self.page='sign';self.logs=[]
        self.email,self.password,self.udid,self.ipa,self.install_ipa=(Var()for _ in range(5))
        self.remember=Var(False);self.account_load_failed=False
        if not preview:
            try:
                saved=remembered_account()
                if saved:self.email.set(saved['email']);self.password.set(saved['password']);self.remember.set(True)
            except (OSError,ValueError,UnicodeError):self.account_load_failed=True
        self.consent=Var(False);self.auto_install=Var(False);self.device_choice=Var();self.status=Var();self.install_status=Var();self.device_status=Var()
        set_language(read_settings()['language']);self.setWindowTitle('RhineSign');self.setWindowFlags(Qt.Window|Qt.FramelessWindowHint|Qt.WindowMinMaxButtonsHint);self.setAttribute(Qt.WA_TranslucentBackground)
        self.app_icon=QIcon()
        for size in (16,20,24,32,48,64,128,256):
            path=BUNDLE/'assets'/('icon-'+str(size)+'.png')
            if path.is_file():self.app_icon.addPixmap(QPixmap(str(path)))
        if self.app_icon.isNull():self.app_icon=QIcon(str(BUNDLE/'assets/icon.ico'))
        self.setWindowIcon(self.app_icon);self.setMinimumSize(960,700)
        available=QApplication.primaryScreen().availableGeometry();self.resize(min(1120,available.width()-50),min(860,available.height()-50));self.move(available.center()-self.rect().center())
        self.logs=[t('等待选择 IPA。')];self.build();self.after(100,self.poll)
        if not preview:self.after(500,self.refresh_devices)
        if self.account_load_failed:self.after(600,lambda:messagebox.showerror('RhineSign',t('本机保存的账号无法解密，请重新输入。'),parent=self))
    def title(self,value):self.setWindowTitle(value)
    def after(self,delay,fn):QTimer.singleShot(delay,self,lambda:None if self._closed else fn())
    def toggle_maximize(self):self.showNormal()if self.isMaximized()else self.showMaximized()
    def build(self):
        self.entries=[];central=QWidget();outer=QVBoxLayout(central);outer.setContentsMargins(7,7,7,7);outer.setSpacing(0)
        shell=QFrame();shell.setObjectName('shell');outer.addWidget(shell);box=QVBoxLayout(shell);box.setContentsMargins(1,1,1,1);box.setSpacing(0)
        title=TitleBar();title.setObjectName('titlebar');title.setFixedHeight(48);bar=QHBoxLayout(title);bar.setContentsMargins(17,5,10,5)
        mark=QLabel();mark.setPixmap(self.app_icon.pixmap(24,24));bar.addWidget(mark);bar.addWidget(label('RhineSign'));bar.addStretch()
        self.langbutton=Button('中文 / EN',self.switch_language);self.langbutton.setObjectName('quiet');bar.addWidget(self.langbutton)
        for text,action,name in [('−',self.showMinimized,'windowControl'),('□',self.toggle_maximize,'windowControl'),('×',self.close,'windowClose')]:
            b=Button(text,action);b.setFixedSize(34,30);b.setObjectName(name);bar.addWidget(b)
        box.addWidget(title);body=QHBoxLayout();body.setSpacing(0);box.addLayout(body,1)
        side=QFrame();side.setObjectName('sidebar');side.setFixedWidth(210);nav=QVBoxLayout(side);nav.setContentsMargins(18,27,18,18);nav.setSpacing(7)
        badge=QLabel();badge.setPixmap(self.app_icon.pixmap(55,55));nav.addWidget(badge);nav.addSpacing(9);nav.addWidget(label('RhineSign','brand'));nav.addWidget(label('APPLICATION STUDIO','eyebrow'));nav.addSpacing(24);nav.addWidget(label('WORKSPACE / 01','eyebrow'));nav.addSpacing(5);self.nav=[]
        for key,text in [('sign','个人签名'),('install','设备安装'),('settings','设置与关于')]:
            b=Button(t(text),lambda checked=False,k=key:self.show(k));b.setObjectName('nav');b.setCheckable(True);nav.addWidget(b);self.nav.append((key,b))
        nav.addStretch();nav.addWidget(label('RS—05   /   DESKTOP','eyebrow'));nav.addWidget(label('RinTaigyoku','muted'));body.addWidget(side)
        content=QWidget();main=QVBoxLayout(content);main.setContentsMargins(29,23,29,12);main.setSpacing(9)
        self.heading=label('','headline');self.subtitle=label('','muted');main.addWidget(self.heading);main.addWidget(self.subtitle);main.addSpacing(9);self.stack=QStackedWidget();main.addWidget(self.stack,1);self.pages={};self.page_layouts={}
        for key in ('sign','install','settings'):
            scroll=QScrollArea();scroll.setWidgetResizable(True);inner=QWidget();layout=QVBoxLayout(inner);layout.setContentsMargins(0,0,8,3);layout.setSpacing(9);scroll.setWidget(inner);self.stack.addWidget(scroll);self.pages[key]=scroll;self.page_layouts[key]=layout
        self.build_sign();self.build_install();self.build_settings();foot=QHBoxLayout();credit=label('© 2026 RinTaigyoku  ·  v'+VERSION,'muted');credit.setWordWrap(False);foot.addWidget(credit);foot.addStretch();link=Button(t('项目主页 ↗'),lambda:webbrowser.open(PROJECT));link.setObjectName('quiet');foot.addWidget(link);foot.addWidget(QSizeGrip(self));main.addLayout(foot)
        body.addWidget(content,1);self.setCentralWidget(central);self.show(self.page)
    def field(self,grid,r,c,text,var,password=False):
        group=QVBoxLayout();group.setSpacing(7);group.addWidget(label(t(text),'muted'));entry=Entry();var.bind(entry)
        if password:entry.setEchoMode(QLineEdit.Password)
        group.addWidget(entry);grid.addLayout(group,r,c);self.entries.append(entry);return entry
    def build_sign(self):
        layout=self.page_layouts['sign'];account,box=card('账号','01 / APPLE ID');grid=QGridLayout();grid.setHorizontalSpacing(17);grid.setColumnStretch(0,1);grid.setColumnStretch(1,1)
        email=self.field(grid,0,0,'Apple ID',self.email);password=self.field(grid,0,1,'登录密码',self.password,True);box.addLayout(grid)
        self.remember_check=Check(t('记住 Apple ID 和密码（仅当前 Windows 用户）'));self.remember.bind(self.remember_check);self.remember_check.toggled.connect(self.remember_changed)
        email.editingFinished.connect(self.persist_account);password.editingFinished.connect(self.persist_account)
        box.addLayout(row(None,self.remember_check));layout.addWidget(account)
        app,box=card('应用与目标设备','02 / IPA + USB');entry=Entry();entry.setPlaceholderText(t('选择要签名的 IPA'));self.ipa.bind(entry);self.entries.append(entry);self.browse=Button(t('选择 IPA…'),self.pick_ipa);box.addLayout(row(entry,self.browse))
        entry=Entry();entry.setPlaceholderText('iPhone UDID');self.udid.bind(entry);self.entries.append(entry);self.paste=Button(t('读取设备'),self.use_device);box.addLayout(row(entry,self.paste));box.addWidget(label(t('勾选记住后账号密码由 Windows 加密保存在本机；验证码与登录会话不保存。'),'muted'));layout.addWidget(app)
        self.check=Check(t('已阅读设置页的服务说明，同意本次个人签名'));self.consent.bind(self.check);layout.addWidget(self.check);self.auto=Check(t('签名完成后安装到已连接的目标 iPhone'));self.auto_install.bind(self.auto);layout.addWidget(self.auto)
        self.start_button=Button(t('开始个人签名  →'),self.start,True);self.cancel_button=Button(t('取消任务'),self.cancel);self.cancel_button.setEnabled(False);output=Button(t('输出文件夹'),self.open_output);output.setObjectName('quiet');layout.addLayout(row(self.start_button,self.cancel_button,None,output))
        self.status.set(t('准备就绪'));status=label('','muted');self.status.bind(status);self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumBlockCount(180);self.log.setFixedHeight(78)
        details=Button(t('收起详情'));details.setObjectName('quiet')
        def toggle_details():
            self.log.setVisible(not self.log.isVisible());details.setText(t('收起详情')if self.log.isVisible()else t('展开详情'))
        details.clicked.connect(toggle_details);layout.addLayout(row(status,None,details));self.progress=Progress();layout.addWidget(self.progress);layout.addWidget(self.log)
        for text in self.logs[-180:]:self.log.appendPlainText(text)
        layout.addStretch()
    def build_install(self):
        layout=self.page_layouts['install'];device,box=card('USB 连接','01 / DEVICE');box.addWidget(label(t('用数据线连接 iPhone，解锁后信任此电脑。'),'muted'))
        self.selector=Combo();self.selector.addItems(self.device_labels());self.device_choice.bind(self.selector);self.refresh=Button(t('刷新设备'),self.refresh_devices);box.addLayout(row(self.selector,self.refresh));self.connect_button=Button(t('连接并读取设备信息'),self.connect_device);box.addLayout(row(self.connect_button,None))
        self.device_status.set(t('尚未连接设备'));status=label('','muted');self.device_status.bind(status);box.addWidget(status);layout.addWidget(device)
        package,box=card('安装已签名 IPA','02 / INSTALL');box.addWidget(label(t('安装不需要重新登录 Apple ID；签名必须有效且适用于这台设备。'),'muted'));self.install_entry=Entry();self.install_ipa.bind(self.install_entry);self.install_pick=Button(t('选择 IPA…'),self.pick_install);box.addLayout(row(self.install_entry,self.install_pick))
        self.install_button=Button(t('安装到 iPhone  →'),self.start_install,True);self.install_cancel=Button(t('取消任务'),self.cancel);self.install_cancel.setEnabled(False);box.addLayout(row(self.install_button,self.install_cancel,None));self.install_status.set(t('等待安装'));status=label('','muted');self.install_status.bind(status);box.addWidget(status);self.install_progress=Progress();box.addWidget(self.install_progress);layout.addWidget(package)
        self.install_log=QPlainTextEdit();self.install_log.setReadOnly(True);self.install_log.setMaximumBlockCount(180);self.install_log.setFixedHeight(78);layout.addWidget(self.install_log)
        for text in self.logs[-180:]:self.install_log.appendPlainText(text)
        layout.addWidget(label(t('安装失败时保留当前 App，不自动卸载。需要 Apple 的 USB 驱动和设备服务。'),'muted'));layout.addStretch()
    def build_settings(self):
        layout=self.page_layouts['settings'];about,box=card('署名','RHINESIGN / '+VERSION);box.addWidget(label('RinTaigyoku','brand'));box.addLayout(row(Button(t('GitHub 项目 ↗'),lambda:webbrowser.open(PROJECT)),Button(t('下载与更新 ↗'),lambda:webbrowser.open(PROJECT+'/releases')),Button(t('许可证'),self.open_license),None));layout.addWidget(about)
        for title,code,text in [('服务说明','AUTH / PRIVACY','认证请求发送给 Apple，认证辅助数据来自 ani.iloader.app。记住账号默认关闭；开启后账号密码由 Windows 当前用户加密保存，取消勾选会删除。验证码与登录会话不保存。签名密钥同样在本机加密保存。'),('使用限制','ACCOUNT / DEVICE','个人账户的有效期、设备与 App 数量由 Apple 限制。签名暂不支持带 App Extension 的 IPA；设备安装不提供绕过签名或开发者模式的功能。')]:
            frame,box=card(title,code);box.addWidget(label(t(text),'muted'));layout.addWidget(frame)
        layout.addStretch()
    def show(self,page=None):
        if page is None:return super().show()
        self.page=page;self.stack.setCurrentWidget(self.pages[page]);titles={'sign':('个人签名','为自己的 iPhone 准备应用。'),'install':('设备安装','连接、读取，再把应用送到手机。'),'settings':('设置与关于','RhineSign，由 RinTaigyoku 维护。')};self.heading.setText(t(titles[page][0]));self.subtitle.setText(t(titles[page][1]))
        for key,b in self.nav:b.setChecked(key==page)
    def add_log(self,text):
        self.logs.append(text);self.logs=self.logs[-180:];self.log.appendPlainText(text)
        if hasattr(self,'install_log'):self.install_log.appendPlainText(text)
    def closeEvent(self,event):
        if self.running and not messagebox.askyesno('RhineSign',t('任务正在进行，确定取消并退出？'),parent=self,default='no'):event.ignore();return
        if not self.persist_account():event.ignore();return
        self.cancel()
        if self.aux and self.aux.poll()is None:self.aux.terminate()
        self.password.set('');self._closed=True;event.accept()

def create_application():
    application=QApplication.instance()or QApplication(sys.argv);application.setApplicationName('RhineSign');application.setOrganizationName('RinTaigyoku');application.setStyle('Fusion')
    if not QFontDatabase.families()and os.name=='nt':
        for name in('segoeui.ttf','seguisb.ttf','msyh.ttc','consola.ttf'):
            path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/name
            if path.is_file():QFontDatabase.addApplicationFont(str(path))
    font=QFont();font.setFamilies(['Segoe UI','Microsoft YaHei']);application.setFont(font)
    style=(BUNDLE/'assets/theme.qss').read_text('utf8').replace('@ASSETS@',(BUNDLE/'assets').as_posix())
    application.setStyleSheet(style)
    palette=QPalette();palette.setColor(QPalette.Window,QColor('#171e1b'));palette.setColor(QPalette.WindowText,QColor('#edf0e6'));palette.setColor(QPalette.Base,QColor('#152019'));palette.setColor(QPalette.Text,QColor('#edf0e6'));palette.setColor(QPalette.Button,QColor('#2c3a2f'));palette.setColor(QPalette.ButtonText,QColor('#edf0e6'));palette.setColor(QPalette.Highlight,QColor('#536b3d'));application.setPalette(palette)
    if hasattr(application.styleHints(),'setColorScheme'):application.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    return application
def main():
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('RinTaigyoku.RhineSign')
    except (OSError,AttributeError):pass
    application=create_application();window=RhineWindow();window.show();sys.exit(application.exec())
