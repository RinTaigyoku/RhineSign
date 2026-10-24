//! GUI-only Apple ID authentication, provisioning and signing. No material export.
use std::{fs,io::{self,Write},path::PathBuf,time::{Duration,SystemTime}};
use isideload::{auth::apple_account::{AppleAccount,TwoFactorCallbackParams,TwoFactorCallbackResponse},dev::developer_session::{DeveloperSession,TeamsApi,AppIdsApi,DevicesApi,DeveloperDeviceType},sideload::{cert_identity::CertificateIdentity,builder::MaxCertsBehavior,application::Application,sign},util::{callbacks::MaxCertsCallbackBox,storage::SideloadingStorage}};
use rootcause::prelude::*;
use serde::Deserialize;
use serde_json::{json,Value};
use zeroize::{Zeroize,Zeroizing};
use x509_cert::der::Encode;
use isideload::dev::certificates::DevelopmentCertificate;
mod shared;
mod signature_guard;
mod devices;
use shared::*;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config { email:String,password:String,udid:String,ipa:PathBuf,work_dir:PathBuf,consent:bool }
impl Drop for Config {fn drop(&mut self){self.password.zeroize();}}
fn event(kind:&str,data:Value){let mut out=io::stdout().lock();let _=writeln!(out,"{}",json!({"type":kind,"data":data}));let _=out.flush();}
fn read_line()->Result<Zeroizing<String>,Report>{let mut s=Zeroizing::new(String::new());if io::stdin().read_line(&mut s)?==0{bail!("input_closed");}if s.len()>1024*1024{bail!("input_too_large");}Ok(s)}
fn ask(kind:&str,data:Value)->Result<Value,Report>{event(kind,data);Ok(serde_json::from_str(&read_line()?)?)}
fn stage(s:&str){event("stage",json!({"name":s}));}
struct ProtectedKeyStorage;
impl SideloadingStorage for ProtectedKeyStorage {
    fn store(&self,key:&str,value:&str)->Result<(),Report>{
        let r=ask("storage",json!({"op":"store","key":key,"value":value}))?;
        if r.get("ok").and_then(Value::as_bool)!=Some(true){bail!("protected_key_storage_failed");}Ok(())
    }
    fn retrieve(&self,key:&str)->Result<Option<String>,Report>{
        let r=ask("storage",json!({"op":"retrieve","key":key}))?;
        if r.get("ok").and_then(Value::as_bool)!=Some(true){bail!("protected_key_storage_failed");}
        Ok(r.get("value").and_then(Value::as_str).map(str::to_owned))
    }
}
fn original_bundle(path:&std::path::Path)->Result<String,Report>{
    let mut z=zip::ZipArchive::new(fs::File::open(path)?)?;
    let mut seen=std::collections::HashSet::new();
    for i in 0..z.len(){let f=z.by_index(i)?;
        if f.enclosed_name().is_none()||!seen.insert(f.name().to_owned()){bail!("invalid_ipa_archive");}
        if f.name().contains(".appex/"){bail!("extensions_need_separate_profiles");}
        if f.unix_mode().is_some_and(|mode|mode&0o170000==0o120000){bail!("unsupported_archive_symlink");}
    }
    let names:Vec<_>=z.file_names().filter(|n|n.starts_with("Payload/")&&n.ends_with(".app/Info.plist")&&n.matches('/').count()==2).map(str::to_owned).collect();
    if names.len()!=1{bail!("ipa_main_app_ambiguous");}
    let mut f=z.by_name(&names[0])?;if f.size()>8*1024*1024{bail!("info_plist_too_large");}
    let mut bytes=Vec::new();std::io::Read::read_to_end(&mut f,&mut bytes)?;
    let p=plist::Value::from_reader(io::Cursor::new(bytes))?;
    let id=p.as_dictionary().and_then(|d|d.get("CFBundleIdentifier")).and_then(plist::Value::as_string).ok_or_else(||report!("missing_bundle_id"))?;
    if !valid_bundle(id){bail!("invalid_bundle_id");}Ok(id.to_owned())
}
async fn two_factor(p:TwoFactorCallbackParams)->Result<TwoFactorCallbackResponse,Report>{
    let numbers:Vec<_>=p.numbers.iter().map(|n|json!({"id":n.id,"tail":n.last_two_digits})).collect();
    let answer=ask("code",json!({"sms":p.sms,"numbers":numbers}))?;
    parse_code(answer.get("value").and_then(Value::as_str).unwrap_or("q")).ok_or_else(||report!("invalid_code").into())
}
fn approved_replacement(reply:&Value,certs:&[DevelopmentCertificate])->Result<Option<Vec<String>>,Report>{
    if reply.get("action").and_then(Value::as_str)==Some("cancel"){return Ok(None);}
    if reply.get("confirmed").and_then(Value::as_bool)!=Some(true){bail!("replacement_not_confirmed");}
    let serial=reply.get("serial").and_then(Value::as_str).filter(|s|!s.is_empty()).ok_or_else(||report!("replacement_not_confirmed"))?;
    if !certs.iter().any(|c|c.serial_number.as_deref()==Some(serial)){bail!("replacement_not_in_list");}
    Ok(Some(vec![serial.to_owned()]))
}
async fn max_certs(certs:Vec<DevelopmentCertificate>)->Result<Option<Vec<String>>,Report>{
    let rows:Vec<_>=certs.iter().filter(|c|c.serial_number.as_ref().is_some_and(|s|!s.is_empty())).map(|c|json!({
        "serial":c.serial_number,"name":c.name,"machine":c.machine_name,"status":c.status,
        "expires":c.expiration_date.as_ref().map(|d|format!("{d:?}"))
    })).collect();
    stage("个人签名资格数量已满（7460）：等待选择；未撤销任何证书");
    let reply=ask("certificates",json!(rows))?;
    let selected=approved_replacement(&reply,&certs)?;
    if selected.is_some(){stage("已由你确认替换一张旧证书；正在向 Apple 提交并重新申请");}
    Ok(selected)
}
async fn run(c:&mut Config)->Result<(),Report>{
    stage("检查所选 IPA 的主程序与包名");
    let source_bundle=original_bundle(&c.ipa)?;
    stage("Apple ID 登录 / 获取 Session（最多 180 秒）");
    let mut account=tokio::time::timeout(Duration::from_secs(180),AppleAccount::builder(&c.email).err_429_retries(None).login(&c.password,two_factor)).await.map_err(|_|report!("auth_timeout"))??;
    c.password.zeroize();
    stage("读取个人开发者团队");
    let mut session=DeveloperSession::from_account(&mut account).await?;
    let teams=session.list_teams().await?;
    if teams.is_empty(){bail!("no_developer_team");}
    let choice=if teams.len()==1{0}else{
        let choices:Vec<_>=teams.iter().enumerate().map(|(i,t)|json!({"index":i,"name":t.name.as_deref().unwrap_or("Unnamed"),"id":t.team_id})).collect();
        ask("teams",json!(choices))?.get("index").and_then(Value::as_u64).ok_or_else(||report!("invalid_team"))? as usize
    };
    let team=teams.get(choice).ok_or_else(||report!("invalid_team"))?;
    let suffix=format!(".{}",team.team_id);
    let bundle=if source_bundle.ends_with(&suffix){source_bundle}else{format!("{source_bundle}{suffix}")};
    if !valid_bundle(&bundle){bail!("invalid_bundle");}
    // Windows DPAPI protects the internal key for subsequent signs. No P12 UI/export.
    stage("申请个人开发签名资格（不自动吊销已有证书）");
    let callback:MaxCertsCallbackBox=Box::new(|certs|Box::pin(max_certs(certs)));
    let identity=CertificateIdentity::retrieve("RhineSign",&c.email,&mut session,team,&ProtectedKeyStorage,&MaxCertsBehavior::Prompt(callback)).await?;
    stage("注册目标设备、App ID 并获取描述文件");
    session.ensure_device_registered(team,"RhineSign iPhone",&c.udid,DeveloperDeviceType::Ios).await?;
    let ids=session.list_app_ids(team,DeveloperDeviceType::Ios).await?;
    let app_id=if let Some(a)=ids.app_ids.into_iter().find(|a|a.identifier==bundle){a}else{session.add_app_id(team,"RhineSign",&bundle,DeveloperDeviceType::Ios).await?};
    let profile=session.download_team_provisioning_profile(team,&app_id,DeveloperDeviceType::Ios).await?;
    check_downloaded_profile(profile.encoded_profile.as_ref(),&team.team_id,&bundle,&c.udid,&identity.certificate.to_der()?)?;
    stage("解包 IPA、签名主程序与内置动态库");
    let mut app=Application::new(c.ipa.clone())?;
    if !app.bundle.app_extensions().is_empty(){bail!("extensions_need_separate_profiles");}
    let old=app.main_bundle_id()?;app.update_bundle_id(&old,&bundle)?;app.bundle.write_info()?;
    let mut extra=Vec::new();
    sign::sign(&mut app,&identity,&profile,&mut extra,&None,team,Some(|p:f32|async move{event("progress",json!({"value":(p*100.0).clamp(0.0,100.0)}));})).await?;
    stage("核对主程序与所有内置库的权限格式、团队及签名结构");
    let info=plist::Value::from_file(app.bundle.bundle_dir.join("Info.plist"))?;
    let executable=info.as_dictionary().and_then(|d|d.get("CFBundleExecutable")).and_then(plist::Value::as_string).ok_or_else(||report!("missing_executable"))?;
    signature_guard::bundle(&app.bundle.bundle_dir,executable,&team.team_id)?;
    let payload=app.bundle.bundle_dir.parent().ok_or_else(||report!("payload_missing"))?;
    if payload.file_name().and_then(|s|s.to_str())!=Some("Payload"){bail!("unexpected_payload_path");}
    let root=payload.parent().ok_or_else(||report!("archive_root_missing"))?;
    let output_dir=c.work_dir.join("签名输出");fs::create_dir_all(&output_dir)?;
    let stamp=SystemTime::now().duration_since(SystemTime::UNIX_EPOCH)?.as_nanos();
    let output=output_dir.join(format!("{}-RhineSign-{}.ipa",c.ipa.file_stem().unwrap_or_default().to_string_lossy(),stamp));
    let partial=std::env::temp_dir().join("signed.ipa.partial");
    stage("重新打包并校验全部 CRC、资源和应用属性（大型 IPA 需要几分钟）");
    let packed=(||->Result<(),Report>{
        pack_signed(root,&partial).context("archive_pack_failed")?;
        stage("校验重打包后的 CRC、资源和应用属性");
        verify_resources(&c.ipa,&partial).context("archive_verify_failed")?;
        stage("保存已签名 IPA");
        if output.exists(){bail!("output_exists");}
        fs::rename(&partial,&output).context("archive_save_failed")?;Ok(())})();
    if packed.is_err(){let _=fs::remove_file(&partial);}packed?;
    event("done",json!({"path":output,"bundle":bundle}));Ok(())
}
fn main(){
    std::panic::set_hook(Box::new(|_|event("error",json!({"message":"签名引擎异常退出；未打印内部认证响应。"}))));
    if std::env::args().nth(1).as_deref()==Some("--self-test"){if self_test().is_err(){std::process::exit(1);}return;}
    // Credential-free reproduction of the same extraction/packing/verification path.
    if matches!(std::env::args().nth(1).as_deref(),Some("--check-repack"|"--check-signing-repack")){
        let result=(||->Result<(),Report>{
            let input=PathBuf::from(std::env::args_os().nth(2).ok_or_else(||report!("ipa_required"))?).canonicalize()?;
            let workspace=PathBuf::from(std::env::args_os().nth(3).ok_or_else(||report!("invalid_work_dir"))?);
            if !workspace.is_absolute()||workspace.exists(){bail!("invalid_work_dir");}
            original_bundle(&input)?;fs::create_dir_all(&workspace)?;
            unsafe{std::env::set_var("TEMP",&workspace);std::env::set_var("TMP",&workspace);std::env::set_var("TMPDIR",&workspace);}
            isideload::init()?;
            stage("离线解包检查：不登录 Apple，不修改签名");
            let app=Application::new(input.clone())?;
            if std::env::args().nth(1).as_deref()==Some("--check-signing-repack"){
                stage("离线测试签名后重打包：仅处理副本，不登录 Apple");
                let settings=apple_codesign_quick::BundleSigningSettings::new("OFFLINETEST",plist::Dictionary::new(),None);
                apple_codesign_quick::sign_bundle(&app.bundle.bundle_dir,&settings)?;
            }
            let root=app.bundle.bundle_dir.parent().and_then(|p|p.parent()).ok_or_else(||report!("archive_root_missing"))?;
            let packed=workspace.join("repacked.ipa");
            stage("离线重新打包检查");pack_signed(root,&packed).context("archive_pack_failed")?;
            stage("离线 CRC 与资源校验");verify_resources(&input,&packed).context("archive_verify_failed")?;
            event("done",json!({"offline_repack_verified":true}));Ok(())
        })();
        if let Err(e)=result{event("error",json!({"message":safe_error(&e)}));std::process::exit(1);}return;
    }
    if let Some(command)=std::env::args().nth(1){
        if ["--devices","--connect-device","--install"].contains(&command.as_str()){
            if let Err(error)=devices::dispatch(&command){event("error",json!({"message":safe_error(&error)}));std::process::exit(1);}return;
        }
    }
    if std::env::args().nth(1).as_deref()!=Some("--gui"){return;}
    let result=(||->Result<(),Report>{
        let mut c:Config=serde_json::from_str(&read_line()?)?;
        if !c.consent || c.email.trim().is_empty() || c.password.is_empty() || !valid_udid(&c.udid){bail!("invalid_form");}
        if !c.work_dir.is_absolute() || !c.work_dir.is_dir(){bail!("invalid_work_dir");}
        c.ipa=c.ipa.canonicalize()?;
        if c.ipa.extension().and_then(|s|s.to_str()).is_none_or(|s|!s.eq_ignore_ascii_case("ipa")){bail!("ipa_required");}
        let tmp=c.work_dir.join("临时构建").join(format!("run-{}-{}",std::process::id(),SystemTime::now().duration_since(SystemTime::UNIX_EPOCH)?.as_nanos()));
        fs::create_dir_all(&tmp)?;
        event("workspace",json!({"path":tmp}));
        // Set before Tokio creates threads; extraction stays beside the GUI on E:.
        unsafe{std::env::set_var("TEMP",&tmp);std::env::set_var("TMP",&tmp);std::env::set_var("TMPDIR",&tmp);}
        let _=rustls::crypto::ring::default_provider().install_default();
        isideload::init()?;
        let runtime=tokio::runtime::Runtime::new()?;
        let result=runtime.block_on(run(&mut c));drop(runtime);
        // Only the exact run directory just created by this process is removed.
        let _=fs::remove_dir_all(&tmp);result
    })();
    if let Err(e)=result{event("error",json!({"message":safe_error(&e)}));std::process::exit(1);}
}
#[cfg(test)]
include!("tests.rs");
