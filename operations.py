import json,os,queue,re,shutil,subprocess,threading,webbrowser
from pathlib import Path
from security import BASE,BUNDLE,VERSION,key_storage,validate,save_account
from i18n import tr as t,set_language,language
from qt_helpers import messagebox,filedialog
PROJECT='https://github.com/RinTaigyoku/RhineSign'
APPLE_DEVICES='https://apps.microsoft.com/detail/9np83lwlpz9k'
SETTINGS=BASE/'.rhinesign-settings.json'
def read_settings():
    try:
        data = json.loads(SETTINGS.read_text('utf8'))
        return {'language': data.get('language') if data.get('language') in ('zh', 'en') else 'zh'}
    except (OSError, ValueError, TypeError, AttributeError):
        return {'language': 'zh'}

def save_settings(value):
    temp = SETTINGS.with_suffix('.json.tmp')
    temp.write_text(json.dumps({'language': value}, ensure_ascii=False), 'utf8')
    os.replace(temp, SETTINGS)

def engine_path():
    return BUNDLE / 'engine' / 'rhinesign-engine.exe'

def spawn(command):
    return subprocess.Popen([str(engine_path()), command], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, encoding='utf-8', cwd=BASE, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

def cleanup_workspace(path, pid, base=BASE):
    if path is None:
        return
    folder = base / '临时构建'
    path = Path(path)
    if folder.is_symlink() or getattr(folder, 'is_junction', lambda: False)():
        return
    if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
        return
    if path.resolve().parent != folder.resolve() or not re.fullmatch('run-' + str(pid) + '-\\d+', path.name):
        return
    if path.is_dir():
        shutil.rmtree(path)

class Operations:

    def open_device_download(self):webbrowser.open(APPLE_DEVICES)

    def open_driver_help(self):webbrowser.open('https://support.apple.com/'+('zh-cn'if language()=='zh'else'en-us')+'/118290')

    def persist_account(self):
        if self.preview:return True
        try:
            if not self.remember.get():save_account()
            elif self.email.get().strip() and self.password.get():save_account(self.email.get(),self.password.get())
            return True
        except (OSError,ValueError,UnicodeError):
            messagebox.showerror('RhineSign',t('账号记忆设置保存失败，请检查程序目录权限。'),parent=self.root)
            return False

    def remember_changed(self,checked):
        self.persist_account()

    def switch_language(self):
        if self.running or self.aux:
            return
        set_language('en' if language() == 'zh' else 'zh')
        try:
            save_settings(language())
        except OSError:
            messagebox.showerror('RhineSign', t('语言设置保存失败。'), parent=self.root)
        self.root.title('RhineSign')
        self.build()

    def pick_ipa(self):
        value = filedialog.askopenfilename(parent=self.root, title=t('选择要签名的 IPA'), filetypes=[('IPA', '*.ipa')])
        if value:
            self.ipa.set(value)

    def pick_install(self):
        value = filedialog.askopenfilename(parent=self.root, title=t('选择已签名 IPA'), filetypes=[('IPA', '*.ipa')])
        if value:
            self.install_ipa.set(value)

    def open_output(self):
        path = BASE / '签名输出'
        path.mkdir(exist_ok=True)
        os.startfile(path)

    def open_license(self):
        path = BASE / 'LICENSE'
        if path.is_file():
            os.startfile(path)
        else:
            webbrowser.open(PROJECT + '/blob/main/LICENSE')

    def device_labels(self):
        return [f"iPhone / USB · {d['udid'][-8:]}" for d in self.devices]

    def selected_device(self):
        i = self.selector.current()
        return self.devices[i] if 0 <= i < len(self.devices) else None

    def refresh_devices(self):
        if self.running or self.aux:
            return
        self.auxiliary('--devices')

    def connect_device(self):
        d = self.selected_device()
        if not d:
            messagebox.showinfo('RhineSign', t('请先选择已连接的 iPhone。'), parent=self.root)
            return
        self.auxiliary('--connect-device', {'udid': d['udid']})

    def use_device(self):
        d = self.selected_device()
        if d:
            self.udid.set(d['udid'])
        else:
            self.show('install')
            self.refresh_devices()

    def auxiliary(self, command, payload=None):
        if self.running or self.aux:
            return
        try:
            self.aux = spawn(command)
        except OSError:
            self.device_status.set(t('设备引擎启动失败，请完整解压程序。'))
            return
        if payload:
            self.aux.stdin.write(json.dumps(payload) + '\n')
            self.aux.stdin.flush()
        self.refresh.configure(state='disabled')
        self.connect_button.configure(state='disabled')
        self.langbutton.configure(state='disabled')
        threading.Thread(target=self.read_events, args=(self.aux, 'aux'), daemon=True).start()

    def send(self, value):
        if self.child and self.child.poll() is None:
            try:
                self.child.stdin.write(json.dumps(value, ensure_ascii=False) + '\n')
                self.child.stdin.flush()
                return True
            except (OSError, ValueError):
                pass
        return False

    def start(self):
        if self.running or self.aux:
            return
        issue = validate(self.email.get(), self.password.get(), self.udid.get(), self.ipa.get(), self.consent.get())
        if issue:
            messagebox.showerror('RhineSign', issue, parent=self.root)
            return
        if not self.persist_account():return
        if shutil.disk_usage(BASE).free < Path(self.ipa.get()).stat().st_size * 3:
            messagebox.showerror('RhineSign', t('空间不足，请预留 IPA 大小三倍的可用空间。'), parent=self.root)
            return
        self.auto_request = None
        if self.auto_install.get():
            d = self.selected_device()
            if not d or d['udid'].lower() != self.udid.get().strip().lower():
                messagebox.showerror('RhineSign', t('安装目标与签名 UDID 不一致，请先读取目标设备。'), parent=self.root)
                return
            if not self.confirm_install(Path(self.ipa.get()).name, d['udid']):
                return
            self.auto_request = d['udid']
        config = {'email': self.email.get().strip(), 'password': self.password.get(), 'udid': self.udid.get().strip(), 'ipa': self.ipa.get(), 'work_dir': str(BASE), 'consent': True}
        self.launch('--gui', config)
        config['password'] = ''

    def confirm_install(self, name, udid):
        return messagebox.askyesno(t('确认安装'), name + '\n\niPhone: ' + udid + '\n\n' + t('同包名应用可能被覆盖更新。程序不会先卸载现有 App。是否继续？'), default='no', parent=self.root)

    def start_install(self):
        if self.running or self.aux:
            return
        d = self.selected_device()
        path = Path(self.install_ipa.get())
        if not d:
            messagebox.showinfo('RhineSign', t('请先选择已连接的 iPhone。'), parent=self.root)
            return
        if not path.is_file() or path.suffix.lower() != '.ipa':
            messagebox.showerror('RhineSign', t('请选择一个存在的 IPA 文件。'), parent=self.root)
            return
        if self.confirm_install(path.name, d['udid']):
            self.launch('--install', {'udid': d['udid'], 'ipa': str(path), 'confirmed': True})

    def launch(self, command, config):
        try:
            self.child = spawn(command)
        except OSError:
            messagebox.showerror('RhineSign', t('设备引擎启动失败，请完整解压程序。'), parent=self.root)
            return False
        self.operation = command
        self.finished = False
        self.running = True
        self.stage = t('准备任务')
        self.status.set(self.stage)
        self.install_status.set(self.stage)
        self.add_log(self.stage)
        self.set_busy(True)
        self.send(config)
        self.workspace = None
        self.progress.configure(value=0)
        self.install_progress.configure(value=0)
        threading.Thread(target=self.read_events, args=(self.child, 'main'), daemon=True).start()
        return True

    def read_events(self, process, channel):
        try:
            for line in process.stdout:
                if len(line) > 1024 * 1024:
                    continue
                try:
                    e = json.loads(line)
                    if isinstance(e, dict) and e.get('type') in {'stage', 'code', 'teams', 'certificates', 'storage', 'progress', 'done', 'error', 'devices', 'connected', 'installed', 'workspace'}:
                        e['channel'] = channel
                        self.events.put(e)
                except (ValueError, TypeError):
                    continue
        finally:
            self.events.put({'type': 'exit', 'data': process.wait(), 'channel': channel})

    def set_busy(self, busy):
        self.password_reveal.setEnabled(not busy)
        for widget in self.entries + [self.remember_check,self.browse, self.paste, self.check, self.auto, self.start_button, self.install_button, self.install_pick, self.install_entry, self.refresh, self.connect_button, self.langbutton]:
            widget.configure(state='disabled' if busy else 'normal')
        self.selector.configure(state='disabled' if busy else 'readonly')
        self.cancel_button.configure(state='normal' if busy else 'disabled')
        self.install_cancel.configure(state='normal' if busy else 'disabled')

    def poll(self):
        try:
            while True:
                e = self.events.get_nowait()
                kind = e['type']
                data = e.get('data', {})
                aux = e.get('channel') == 'aux'
                if kind == 'workspace' and (not aux):
                    self.workspace = data.get('path')
                elif kind == 'stage':
                    self.stage = t(str(data.get('name', '')))
                    self.status.set(self.stage)
                    self.install_status.set(self.stage)
                    if aux:
                        self.device_status.set(self.stage)
                    else:
                        self.add_log(self.stage)
                elif kind == 'progress':
                    try:
                        value = max(0, min(100, float(data.get('value', 0))))
                    except (ValueError, TypeError):
                        continue
                    self.progress.configure(value=value)
                    self.install_progress.configure(value=value)
                elif kind == 'devices':
                    previous = self.selected_device()
                    self.devices = data if isinstance(data, list) else []
                    self.selector.configure(values=self.device_labels())
                    if len(self.devices) == 1:
                        self.selector.current(0)
                        self.udid.set(self.devices[0]['udid'])
                    elif previous:
                        match = next((i for i, d in enumerate(self.devices) if d['udid'] == previous['udid']), None)
                        if match is not None:
                            self.selector.current(match)
                        else:
                            self.device_choice.set('')
                    else:
                        self.device_choice.set('')
                    self.device_status.set(t('请选择设备并连接。') if self.devices else t('未发现 USB 设备。请检查数据线和 Apple 设备服务。'))
                elif kind == 'connected':
                    self.udid.set(data['udid'])
                    self.device_status.set(str(data.get('name', 'iPhone')) + ' · iOS ' + str(data.get('version', '')) + '\n' + data['udid'])
                elif kind in ('code', 'teams', 'certificates'):
                    getattr(self, {'code': 'code_dialog', 'teams': 'team_dialog', 'certificates': 'certificates_dialog'}[kind])(data)
                elif kind == 'storage':
                    try:
                        self.send(key_storage(data))
                    except (OSError, ValueError, UnicodeError):
                        self.send({'ok': False})
                elif kind == 'done':
                    self.finished = True
                    self.last_output = str(data['path'])
                    self.install_ipa.set(self.last_output)
                    self.status.set(t('签名完成'))
                    self.progress.configure(value=100)
                    self.add_log(t('输出：') + self.last_output)
                    if self.auto_request:
                        self.pending_install = {'ipa': self.last_output, 'udid': self.auto_request, 'confirmed': True}
                    else:
                        messagebox.showinfo('RhineSign', t('签名完成') + '\n' + self.last_output, parent=self.root)
                elif kind == 'installed':
                    self.finished = True
                    self.install_status.set(t('iPhone 已确认安装完成'))
                    self.install_progress.configure(value=100)
                    messagebox.showinfo('RhineSign', t('iPhone 已确认安装完成'), parent=self.root)
                elif kind == 'error':
                    detail = t(str(data.get('message', '')))
                    if aux:
                        self.device_status.set(detail)
                    else:
                        self.finished = True
                        self.pending_install = None
                        self.dismiss_dialog()
                        self.status.set(self.stage)
                        self.install_status.set(detail)
                        self.add_log(detail)
                        messagebox.showerror(t('任务未完成'), self.stage + '\n\n' + detail, parent=self.root)
                elif kind == 'exit':
                    if aux:
                        self.aux = None
                        self.refresh.configure(state='normal')
                        self.connect_button.configure(state='normal')
                        self.langbutton.configure(state='normal')
                    else:
                        try:
                            cleanup_workspace(self.workspace, self.child.pid)
                        except OSError:
                            pass
                        self.running = False
                        self.dismiss_dialog()
                        self.set_busy(False)
                        if not self.finished:
                            self.status.set(t('任务已停止'))
                            self.install_status.set(t('任务已停止'))
                        if self.pending_install:
                            request = self.pending_install
                            self.pending_install = None
                            self.show('install')
                            self.launch('--install', request)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def cancel(self):
        self.pending_install = None
        self.auto_request = None
        if self.child and self.child.poll() is None:
            self.child.terminate()
        self.dismiss_dialog()
