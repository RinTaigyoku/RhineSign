use std::{fs::{self,OpenOptions},io::{self,Read,Write},path::Path,time::{Duration,SystemTime}};
use rootcause::prelude::*;
use isideload::{SideloadError,auth::apple_account::TwoFactorCallbackResponse};

pub(crate) fn profile_matches(d: &plist::Dictionary, team: &str, bundle: &str, udid: &str, cert: &[u8]) -> bool {
    let strings_contain=|key:&str,s:&str| d.get(key).and_then(|v|v.as_array()).is_some_and(|a|a.iter().any(|v|v.as_string()==Some(s)));
    strings_contain("TeamIdentifier",team) && strings_contain("ProvisionedDevices",udid) &&
    d.get("Entitlements").and_then(|v|v.as_dictionary()).and_then(|v|v.get("application-identifier")).and_then(|v|v.as_string())==Some(format!("{team}.{bundle}").as_str()) &&
    d.get("DeveloperCertificates").and_then(|v|v.as_array()).is_some_and(|a|a.iter().any(|v|v.as_data()==Some(cert))) &&
    d.get("ExpirationDate").and_then(|v|v.as_date()).is_some_and(|date|SystemTime::from(date)>SystemTime::now())
}

pub(crate) fn check_downloaded_profile(raw: &[u8], team: &str, bundle: &str, udid: &str, cert: &[u8]) -> Result<(),Report> {
    // Apple supplies a CMS-wrapped XML plist over validated TLS. This checks
    // content association/expiry, not an independent CMS trust-chain verdict.
    let start=raw.windows(5).position(|w|w==b"<?xml").ok_or_else(||report!("profile_xml_missing"))?;
    let end=raw[start..].windows(8).position(|w|w==b"</plist>").ok_or_else(||report!("profile_xml_end_missing"))?+start+8;
    let value=plist::Value::from_reader_xml(&raw[start..end])?;
    if !value.as_dictionary().is_some_and(|d|profile_matches(d,team,bundle,udid,cert)) {bail!("profile_association_or_expiry_mismatch");}
    Ok(())
}

pub(crate) fn valid_bundle(s: &str) -> bool {
    s.len() <= 180 && s.contains('.') && s.split('.').all(|p| !p.is_empty() && p.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-'))
}

pub(crate) fn valid_udid(s: &str) -> bool {
    (s.len() == 40 && s.bytes().all(|b| b.is_ascii_hexdigit())) ||
    (s.len() == 25 && s.as_bytes()[8] == b'-' && s.bytes().enumerate().all(|(i,b)| i==8 || b.is_ascii_hexdigit()))
}

pub(crate) fn parse_code(s: &str) -> Option<TwoFactorCallbackResponse> {
    match s {
        "q" => Some(TwoFactorCallbackResponse::Abort),
        "d" => Some(TwoFactorCallbackResponse::SendToDevices),
        "r" => Some(TwoFactorCallbackResponse::ResendCode),
        _ if s.starts_with('p') => s[1..].parse::<u32>().ok().filter(|x| *x > 0).map(TwoFactorCallbackResponse::SendSms),
        _ if s.len()==6 && s.bytes().all(|b| b.is_ascii_digit()) => Some(TwoFactorCallbackResponse::SubmitCode(s.to_owned())),
        _ => None,
    }
}

pub(crate) fn write_new(path: &Path, data: &[u8]) -> Result<(), Report> {
    let mut file=OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(data)?; file.sync_all()?; Ok(())
}

pub(crate) fn pack_signed(root: &Path, output: &Path) -> Result<(),Report> {
    let file=OpenOptions::new().write(true).create_new(true).open(output)?;
    let mut writer=zip::ZipWriter::new(file);
    for entry in walkdir::WalkDir::new(root).sort_by_file_name() {
        let entry=entry?;if entry.file_type().is_symlink(){bail!("unsupported_archive_symlink");}
        if !entry.file_type().is_file(){continue;}
        let name=entry.path().strip_prefix(root)?.to_string_lossy().replace('\\',"/");
        let opts=zip::write::SimpleFileOptions::default().compression_method(zip::CompressionMethod::Deflated).compression_level(Some(6)).large_file(entry.metadata()?.len()>=0xffff_ffff).unix_permissions(0o755);
        writer.start_file(name,opts)?;io::copy(&mut fs::File::open(entry.path())?,&mut writer)?;
    }
    writer.finish()?.sync_all()?;Ok(())
}

pub(crate) fn verify_resources(input: &Path, output: &Path) -> Result<(),Report> {
    let mut original=zip::ZipArchive::new(fs::File::open(input)?)?;
    let mut signed=zip::ZipArchive::new(fs::File::open(output)?)?;
    // All files are decompressed to validate CRC. Original resource archives must
    // retain their exact decompressed size and CRC, independent of compression.
    let mut names=std::collections::HashSet::new();
    for i in 0..signed.len(){let mut f=signed.by_index(i)?;if !names.insert(f.name().to_owned()){bail!("duplicate_signed_entry");}io::copy(&mut f,&mut io::sink())?;}
    for i in 0..original.len(){
        let mut f=original.by_index(i)?;
        if !f.is_dir()&&!f.name().ends_with("Info.plist")&&!f.name().ends_with("embedded.mobileprovision")&&!f.name().contains("/_CodeSignature/")&&!f.name().ends_with(".dylib") {
            let mut magic=[0u8;4];let n=f.read(&mut magic)?;
            let macho=n==4&&[[0xcf,0xfa,0xed,0xfe],[0xce,0xfa,0xed,0xfe],[0xca,0xfe,0xba,0xbe],[0xca,0xfe,0xba,0xbf],[0xfe,0xed,0xfa,0xcf],[0xfe,0xed,0xfa,0xce]].contains(&magic);
            if !macho {let out=signed.by_name(f.name())?;if out.size()!=f.size()||out.crc32()!=f.crc32(){bail!("protected_resource_changed");}}
        }
        if f.name().ends_with(".app/Info.plist") && f.name().matches(".app/").count()==1 {
            if f.size()>8*1024*1024 {bail!("info_plist_too_large");}
            let mut old_bytes=Vec::new();f.read_to_end(&mut old_bytes)?;
            let old=plist::Value::from_reader(io::Cursor::new(old_bytes))?;
            let mut new_file=signed.by_name(f.name())?;if new_file.size()>8*1024*1024 {bail!("info_plist_too_large");}
            let mut new_bytes=Vec::new();new_file.read_to_end(&mut new_bytes)?;
            let new=plist::Value::from_reader(io::Cursor::new(new_bytes))?;
            for key in ["LSSupportsGameMode","CADisableMinimumFrameDurationOnPhone","CFBundleVersion","CFBundleShortVersionString","CFBundleExecutable"] {
                if old.as_dictionary().and_then(|d|d.get(key)) != new.as_dictionary().and_then(|d|d.get(key)){bail!("protected_info_key_changed");}
            }
        }
    }
    Ok(())
}

pub(crate) fn safe_error(report: &Report) -> String {
    // Typed local failures are safe to classify without exposing paths or responses.
    let mut local_code=None;
    for node in report.iter_reports(){
        if let Some(e)=node.downcast_current_context::<io::Error>(){
            local_code=Some(format!("IO/{:?}/{}",e.kind(),e.raw_os_error().map(|x|x.to_string()).unwrap_or_else(||"none".into())));
        }
        if let Some(e)=node.downcast_current_context::<zip::result::ZipError>(){
            local_code=Some(match e {
                zip::result::ZipError::Io(e)=>format!("ZIP/IO/{:?}/{}",e.kind(),e.raw_os_error().map(|x|x.to_string()).unwrap_or_else(||"none".into())),
                _=>format!("ZIP/{e}"),
            });
        }
    }
    for node in report.iter_reports(){
        let context=node.downcast_current_context::<&str>().copied();
        let label=match context {
            Some("archive_pack_failed")=>Some("本地 IPA 重新打包失败"),
            Some("archive_verify_failed")=>Some("本地 IPA CRC、资源或属性校验失败"),
            Some("archive_save_failed")=>Some("已签名 IPA 保存失败"),
            _=>None,
        };
        if let Some(label)=label{let diagnostic=local_code.as_deref().unwrap_or("LOCAL/validation");return format!("{label}。诊断：{diagnostic}。原始 IPA 保留。");}
    }
    for node in report.iter_reports() {
        if let Some(err)=node.downcast_current_context::<SideloadError>() {
            match err {
                SideloadError::AuthWithMessage(code,_) => return format!("Apple 认证返回码：{code}。这不是一律代表密码错误。"),
                SideloadError::DeveloperError(7460,_) => return "Apple 个人开发证书数量已达上限（7460）；未自动吊销任何证书。取消后不会继续替换。".into(),
                SideloadError::DeveloperError(code,_) => return format!("Apple 开发服务返回码：{code}。未自动吊销任何证书。"),
                _ => (),
            }
        }
    }
    for node in report.iter_reports(){
        if node.downcast_current_context::<idevice::IdeviceError>().is_some(){return "设备操作失败。请确认 Apple Mobile Device Service 已安装并运行，解锁并信任电脑；安装失败时也请检查签名、描述文件与设备容量。".into();}
    }
    // Match fixed contexts only; never return the underlying response or URL.
    for node in report.iter_reports() {
        let context=node.downcast_current_context::<&str>().copied()
            .or_else(||node.downcast_current_context::<String>().map(String::as_str));
        if let Some(s)=context {
            let message=match s {
                "device_disconnected" => Some("所选 iPhone 已断开，请重新连接并刷新设备。"),
                "device_timeout" => Some("设备等待超时，请解锁手机并检查 USB 连接。"),
                "install_not_confirmed" => Some("安装尚未确认，没有向手机传输 IPA。"),
                "install_wrong_device" => Some("这个 IPA 的描述文件不包含所选 iPhone，请为该设备重新签名。"),
                "install_profile_expired" => Some("IPA 描述文件已过期，请重新签名。"),
                "invalid_install_archive"|"invalid_install_request"|"invalid_device" => Some("IPA 或目标设备信息无效，安装已停止。"),
                "install_source_changed" => Some("传输期间 IPA 文件发生变化，请重新选择文件。"),
                "auth_timeout" => Some("Apple 登录等待超时（180 秒）；请检查网络及手机验证请求。"),
                "nested_permissions_present"|"signature_missing_der"|"signature_bad_directory"|"signature_missing"|"signature_team_mismatch"|"signature_bounds" => Some("内置程序或动态库签名结构、团队或权限格式检查未通过；已停止输出 IPA。"),
                "replacement_not_confirmed"|"replacement_not_in_list" => Some("证书替换未获有效确认或选择已失效；未执行该次撤销。"),
                "protected_key_storage_failed" => Some("Windows 加密密钥存储失败；未继续申请新的签名资格。"),
                "extensions_need_separate_profiles" => Some("所选 IPA 含应用扩展，需要额外描述文件；此版本暂不支持此包。"),
                "invalid_ipa_archive"|"unsupported_archive_symlink"|"ipa_main_app_ambiguous"|"missing_bundle_id"|"invalid_bundle_id" => Some("IPA 主程序、包名或归档结构无效，尚未登录 Apple。"),
                "no_developer_team" => Some("账户没有返回可用开发者团队，请检查 Apple 开发者条款及账户状态。"),
                "Failed to get anisette client info"|"Failed to get anisette data for 2FA" => Some("认证辅助服务连接失败；未将其解释为账号或密码错误。"),
                "No 2FA code provided, aborting" => Some("双重认证已取消。"),
                "profile_association_or_expiry_mismatch" => Some("描述文件的设备、团队、包名、签名或有效期校验失败，已停止签名。"),
                "protected_resource_changed"|"protected_info_key_changed" => Some("签名后应用资源或受保护属性发生变化，校验未通过；未输出完成 IPA。"),
                _ => None,
            };
            if let Some(message)=message{return message.into();}
        }
    }
    "当前步骤失败；可能涉及输入、网络、服务或文件。未输出原始认证响应，以免泄露会话。".into()
}

pub(crate) fn self_test() -> Result<(), Report> {
    assert!(valid_bundle("com.example.demo"));
    assert!(!valid_bundle("com..demo")); assert!(!valid_bundle("com.test/*"));
    assert!(valid_udid("00008150-0000000000000000"));
    assert!(!valid_udid("bad"));
    assert!(matches!(parse_code("123456"),Some(TwoFactorCallbackResponse::SubmitCode(_))));
    assert!(matches!(parse_code("q"),Some(TwoFactorCallbackResponse::Abort)));
    assert!(parse_code("12345").is_none()); assert!(parse_code("p0").is_none());
    assert!(matches!(parse_code("p2"),Some(TwoFactorCallbackResponse::SendSms(2))));
    println!("离线自检通过；没有登录、网络请求、创建证书或修改爱思/IPA。"); Ok(())
}
