"""Build the GUI distribution with source and third-party license texts."""
from pathlib import Path
import subprocess,sys,shutil,zipfile,importlib.metadata
r=Path(__file__).resolve().parents[1]
subprocess.run([sys.executable,'-m','PyInstaller','--clean','--noconfirm','--onedir','--noconsole','--name','RhineSign','--icon','assets/icon.ico','--add-data','assets;assets','--add-binary','engine/target/release/rhinesign-engine.exe;engine','app.py'],cwd=r,check=True)
out=r/'dist/RhineSign'
for name in ('README.md','LICENSE','THIRD_PARTY_NOTICES.txt'):shutil.copyfile(r/name,out/name)
for f in(r/'engine/target/license-report').glob('*'):shutil.copyfile(f,out/f.name)
dep=r/'engine/generated-deps/apple-codesign-quick'
assert(dep/'RHINESIGN_PATCH.json').is_file()
for name in('COPYING','COPYING.LESSER'):shutil.copyfile(r/'licenses'/name,out/name)
files=list(r.glob('*.py'))+list(r.glob('*.md'))+[r/'LICENSE',r/'THIRD_PARTY_NOTICES.txt',r/'QT-SOURCE.txt',r/'engine/Cargo.toml',r/'engine/Cargo.lock']
for folder in ('engine/src','scripts','tests','assets','licenses','.github/workflows'):files+=list((r/folder).rglob('*'))
files+=list(dep.rglob('*'))
with zipfile.ZipFile(out/'CorrespondingSource.zip','w',zipfile.ZIP_DEFLATED)as z:
    for f in sorted(set(files)):
        if not f.is_file()or'__pycache__'in f.parts:continue
        assert f.suffix not in('.ipa','.p12','.dpapi','.exe','.pyc')
        z.write(f,f.relative_to(r))
print('Desktop, licenses and corresponding source packaged.')

# Preserve all license texts shipped by the unmodified Qt Python wheels.
for distribution in ('PySide6-Essentials','shiboken6'):
    dist=importlib.metadata.distribution(distribution)
    for item in dist.files or []:
        if any(k in str(item).lower() for k in ('license','copying','notice')):
            source=Path(dist.locate_file(item))
            if source.is_file():
                target=out/'Qt-Licenses'/distribution/str(item).replace('..','_')
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
shutil.copyfile(r/'QT-SOURCE.txt',out/'QT-SOURCE.txt')
