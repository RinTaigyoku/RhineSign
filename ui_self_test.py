"""Credential-free UI checks for the packaged executable."""
from pathlib import Path
import json
from PySide6.QtCore import Qt
from PySide6.QtSvg import QSvgRenderer
from window import create_application,RhineWindow
from i18n import set_language,tr
from security import BUNDLE

def run(folder):
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
    application=create_application();window=RhineWindow(preview=True);window.resize(1120,820);window.show();checks=[]
    try:
        assert window.windowTitle()=='RhineSign'
        assert window.windowFlags()&Qt.FramelessWindowHint;checks.append('integrated_titlebar')
        assert QSvgRenderer(str(BUNDLE/'assets/check.svg')).isValid();checks.append('vector_checkbox_tick')
        for lang in('zh','en'):
            set_language(lang);window.build();application.processEvents()
            assert not window.log.isHidden();checks.append(lang+'_details_default_expanded')
            for page in('sign','install','settings'):
                window.show(page);application.processEvents()
                assert window.heading.text()==tr({'sign':'个人签名','install':'设备安装','settings':'设置与关于'}[page])
                window.grab().save(str(folder/(lang+'-'+page+'.png')));checks.append(lang+'_'+page)
            window.show('sign');window.check.setChecked(True);window.auto.setChecked(True);application.processEvents();window.grab().save(str(folder/(lang+'-checked.png')))
        result={'pass':True,'checks':checks,'count':len(checks),'credentials_used':False,'Apple_login_tested':False,'phone_install_tested':False,'rendered_by_actual_Qt_widgets':True}
        (folder/'result.json').write_text(json.dumps(result,indent=2)+'\n','utf8')
    finally:window.close()
