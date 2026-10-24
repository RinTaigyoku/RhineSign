import ast, json, os, re, tempfile, unittest
from pathlib import Path
import security, i18n

ROOT=Path(__file__).resolve().parents[1]

class DesktopTests(unittest.TestCase):
    def tearDown(self):i18n.set_language('zh')

    def test_password_and_verification_code_visibility(self):
        from qt_helpers import Entry,add_visibility_toggle
        from PySide6.QtWidgets import QLineEdit
        import window
        app=window.create_application()
        for code in (False,True):
            entry=Entry();entry.setText('123456'if code else'synthetic-password')
            action=add_visibility_toggle(entry,code)
            self.assertEqual(entry.echoMode(),QLineEdit.Password)
            before=entry.text();action.setChecked(True)
            self.assertEqual(entry.echoMode(),QLineEdit.Normal);self.assertEqual(entry.text(),before)
            action.setChecked(False);self.assertEqual(entry.echoMode(),QLineEdit.Password)
            self.assertEqual(entry.text(),before);self.assertFalse(action.icon().isNull())
            entry.clear();entry.deleteLater()

    def test_signing_keeps_password_mask(self):
        import window
        from PySide6.QtWidgets import QLineEdit
        app=window.create_application();root=window.RhineWindow(preview=True)
        try:
            with tempfile.TemporaryDirectory()as folder:
                path=Path(folder)/'synthetic.ipa';path.write_bytes(b'synthetic')
                root.email.set('test@example.invalid');root.password.set('synthetic-password')
                root.udid.set('00008150-0000000000000000');root.ipa.set(str(path));root.consent.set(True)
                calls=[];root.launch=lambda command,config:calls.append(command)or True
                root.start();self.assertEqual(calls,['--gui'])
                self.assertEqual(root.password.get(),'synthetic-password')
                self.assertEqual(root.entries[1].echoMode(),QLineEdit.Password)
        finally:root.close();app.processEvents()

    @unittest.skipUnless(os.name=='nt','Windows DPAPI')
    def test_remember_account_is_encrypted_and_removable(self):
        with tempfile.TemporaryDirectory()as folder:
            base=Path(folder);email='remember@example.invalid';password='synthetic-password-123'
            self.assertIsNone(security.remembered_account(base))
            security.save_account(email,password,base)
            raw=(base/'.rhinesign-account.dpapi').read_bytes()
            self.assertNotIn(email.encode(),raw);self.assertNotIn(password.encode(),raw)
            self.assertEqual(security.remembered_account(base),{'email':email,'password':password})
            security.save_account(email,'updated-synthetic',base)
            self.assertEqual(security.remembered_account(base)['password'],'updated-synthetic')
            security.save_account(base=base)
            self.assertIsNone(security.remembered_account(base));self.assertEqual(list(base.iterdir()),[])

    def test_arbitrary_ipa(self):
        with tempfile.TemporaryDirectory()as folder:
            p=Path(folder)/'any-release.ipa';p.write_bytes(b'synthetic')
            args=['user@example.invalid','synthetic','00008150-0000000000000000',str(p),True]
            self.assertIsNone(security.validate(*args))
            for i,value in [(0,''),(1,''),(2,'bad'),(3,str(p.with_suffix('.exe'))),(4,False)]:
                bad=args.copy();bad[i]=value;self.assertIsNotNone(security.validate(*bad))

    @unittest.skipUnless(os.name=='nt','Windows DPAPI')
    def test_protected_storage_and_no_overwrite(self):
        with tempfile.TemporaryDirectory()as folder:
            base=Path(folder);key='b'*64+'/key';value='synthetic-local-test-only'
            self.assertIsNone(security.key_storage({'op':'retrieve','key':key},base)['value'])
            security.key_storage({'op':'store','key':key,'value':value},base)
            self.assertEqual(security.key_storage({'op':'retrieve','key':key},base)['value'],value)
            self.assertNotIn(value.encode(),next((base/'.签名密钥').iterdir()).read_bytes())
            with self.assertRaises(FileExistsError):security.key_storage({'op':'store','key':key,'value':'other'},base)
            with self.assertRaises(ValueError):security.key_storage({'op':'retrieve','key':'../escape'},base)

    def test_every_explicit_ui_translation(self):
        for name in ('window.py','qt_dialogs.py','qt_helpers.py','operations.py','security.py'):
            for node in ast.walk(ast.parse((ROOT/name).read_text('utf8'))):
                if isinstance(node,ast.Call)and isinstance(node.func,ast.Name)and node.func.id in ('t','_t')and node.args and isinstance(node.args[0],ast.Constant):
                    value=node.args[0].value
                    if isinstance(value,str)and re.search('[\u3400-\u9fff]',value):self.assertIn(value,i18n.EN,name+': '+value)

    def test_engine_messages_have_english(self):
        for f in (ROOT/'engine/src').glob('*.rs'):
            if f.name=='tests.rs':continue
            for value in re.findall(r'"([^"\n]*[\u3400-\u9fff][^"\n]*)"',f.read_text('utf8')):
                if value in ('临时构建','签名输出')or'离线自检通过'in value:continue
                self.assertIn(value,i18n.EN,f.name+': '+value)

    def test_dynamic_apple_codes(self):
        i18n.set_language('en')
        for value in (-22411,7460):
            source=f'Apple 认证返回码：{value}。这不是一律代表密码错误。'
            self.assertIn(str(value),i18n.tr(source));self.assertNotRegex(i18n.tr(source),'[\u3400-\u9fff]')
        i18n.set_language('zh');self.assertEqual(i18n.tr('个人签名'),'个人签名')

    def test_privacy_boundaries(self):
        code=(ROOT/'window.py').read_text('utf8')+(ROOT/'operations.py').read_text('utf8');settings=(ROOT/'security.py').read_text('utf8')
        self.assertIn('CREATE_NO_WINDOW',code);self.assertIn('stderr=subprocess.DEVNULL',code)
        self.assertNotIn('logging.',code);self.assertNotIn('P12',code)
        self.assertIn('confirmed',code);self.assertIn('default=\'no\'',code)
        self.assertIn('crypt32',settings)

    def test_cleanup_is_limited_to_owned_workspace(self):
        from operations import cleanup_workspace
        with tempfile.TemporaryDirectory()as folder:
            base=Path(folder);owned=base/'临时构建/run-42-12345';owned.mkdir(parents=True);(owned/'partial').write_text('test')
            outside=base/'other';outside.mkdir();(outside/'keep').write_text('keep')
            cleanup_workspace(outside,42,base);self.assertTrue((outside/'keep').exists())
            cleanup_workspace(owned,99,base);self.assertTrue(owned.exists())
            cleanup_workspace(owned,42,base);self.assertFalse(owned.exists())

    def test_build_widgets_in_both_languages(self):
        import window
        app=window.create_application();root=window.RhineWindow(preview=True)
        self.assertFalse(root.remember.get());self.assertEqual(root.password.get(),'')
        try:
            for lang in ('zh','en'):
                i18n.set_language(lang);root.build();app.processEvents()
                for page in ('sign','install','settings'):root.show(page);app.processEvents()
                self.assertEqual(root.heading.text(),i18n.tr('设置与关于'))
                self.assertEqual(root.windowTitle(),'RhineSign')
                self.assertFalse(root.log.isHidden())
                self.assertTrue(root.windowFlags()&window.Qt.FramelessWindowHint)
                root.email.set('synthetic@example.invalid')
                self.assertTrue(any(e.text()=='synthetic@example.invalid'for e in root.entries))
        finally:root.close();app.processEvents()

if __name__=='__main__':unittest.main()
