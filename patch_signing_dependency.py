"""Reproduce a narrow LGPL signing-format patch from a checksum-pinned crate."""
from pathlib import Path
import hashlib,urllib.request,tarfile,argparse,shutil,json
ROOT=Path(__file__).resolve().parent
EXPECTED='519defc726db80b8a43836bbd6f69eb606a42783db799716a103436042593f0b'
def replace(path,old,new):
    text=path.read_text('utf8');assert text.count(old)==1,(path.name,old[:50]);path.write_text(text.replace(old,new),'utf8',newline='\n')
def prepare(output):
    output=output.resolve();output.mkdir(parents=True,exist_ok=True)
    archive=output.parent/'apple-codesign-quick-0.1.0.crate'
    if not archive.exists():archive.write_bytes(urllib.request.urlopen('https://static.crates.io/crates/apple-codesign-quick/apple-codesign-quick-0.1.0.crate',timeout=45).read())
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==EXPECTED
    if (output/'RHINESIGN_PATCH.json').exists():return
    with tarfile.open(archive)as tar:
        for member in tar.getmembers():
            rel=Path(*Path(member.name).parts[1:]);target=(output/rel).resolve();assert target.is_relative_to(output)
            if member.isdir():target.mkdir(parents=True,exist_ok=True)
            elif member.isfile():target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(tar.extractfile(member).read())
            else:raise ValueError('Unsupported source archive entry')
    macho=output/'src/macho.rs';signature=output/'src/signature.rs'
    replace(macho,'let entitlements_xml = entitlements_xml(config.entitlements)?;\n    let entitlements = entitlements_blob(&entitlements_xml);','''// RhineSign: permissions belong to executable bundles, never nested libraries.
    let entitlements = if macho.is_executable() {
        entitlements_blob(&entitlements_xml(config.entitlements)?)
    } else { Vec::new() };''')
    replace(signature,'let count = 4\n','let count = 3 + usize::from(plan.entitlements_blob_len != 0)\n')
    replace(signature,'        (CSSLOT_ENTITLEMENTS, Cow::Borrowed(params.entitlements_blob)),\n','')
    replace(signature,'    if let Some(der_entitlements_blob) = params.der_entitlements_blob {','''    if !params.entitlements_blob.is_empty() {
        blobs.push((CSSLOT_ENTITLEMENTS, Cow::Borrowed(params.entitlements_blob)));
    }
    if let Some(der_entitlements_blob) = params.der_entitlements_blob {''')
    replace(signature,'    algorithm.push_digest(&mut out, params.entitlements_blob);','''    if params.entitlements_blob.is_empty() { push_zero_hash(&mut out, hash_len); }
    else { algorithm.push_digest(&mut out, params.entitlements_blob); }''')
    # A real generated MH_DYLIB signature, not a mock setter expectation.
    replace(macho,'mod tests {\n    use super::*;','''mod tests {
    use super::*;
    #[test]
    fn eo_nested_dylib_has_no_permissions_and_main_keeps_der() {
        for executable in [false, true] {
            let mut input=minimal_macho_with_empty_signature();
            LittleEndian::write_u32(&mut input[12..16],if executable {MH_EXECUTE}else{6});
            let mut entitlements=Dictionary::new();
            entitlements.insert("get-task-allow".into(),plist::Value::Boolean(true));
            let config=MachOSigningConfig::new("org.example.test","TESTTEAM",&entitlements,None);
            let signed=sign_macho_data(Path::new("synthetic"),&input,&config).unwrap();
            let pos=32+72+72;
            let off=LittleEndian::read_u32(&signed[pos+8..pos+12])as usize;
            let blob=&signed[off..];let count=BigEndian::read_u32(&blob[8..12])as usize;
            let slots:Vec<_>=(0..count).map(|i|BigEndian::read_u32(&blob[12+i*8..16+i*8])).collect();
            assert_eq!(slots.contains(&5),executable);assert_eq!(slots.contains(&7),executable);
            let cd_off=BigEndian::read_u32(&blob[16..20])as usize;let cd=&blob[cd_off..];
            let hash_off=BigEndian::read_u32(&cd[16..20])as usize;let hash_size=cd[36]as usize;
            assert_eq!(cd[hash_off-5*hash_size..hash_off-4*hash_size].iter().all(|b|*b==0),!executable);
        }
    }''')
    (output/'RHINESIGN_PATCH.json').write_text(json.dumps({'upstream_crate_sha256':EXPECTED,'change':'omit XML/DER entitlement blobs and zero the permission hash for non-executable nested code; executable DER retained','license':'LGPL-2.1-or-later','author':'RhineSign'},indent=2),'utf8')
    print('Prepared pinned LGPL signing dependency and synthetic Mach-O regression')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'engine/generated-deps/apple-codesign-quick');a=p.parse_args();prepare(a.output)
