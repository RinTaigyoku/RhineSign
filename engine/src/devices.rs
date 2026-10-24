//! USB device discovery and streamed installation through Apple's local service.
use std::{fs,io::Read,path::{Path,PathBuf},time::{Duration,SystemTime,UNIX_EPOCH}};
use idevice::{IdeviceService,provider::{IdeviceProvider,UsbmuxdProvider},usbmuxd::{Connection,UsbmuxdAddr},lockdown::LockdownClient,afc::{AfcClient,opcode::AfcFopenMode},installation_proxy::InstallationProxyClient};
use rootcause::prelude::*;
use serde::Deserialize;
use serde_json::{json,Value};
use crate::{event,read_line,shared::valid_udid};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {udid:String,#[serde(default)]ipa:Option<PathBuf>,#[serde(default)]confirmed:bool}

async fn provider(udid:&str)->Result<UsbmuxdProvider,Report>{
    if !valid_udid(udid){bail!("invalid_device");}
    let addr=UsbmuxdAddr::default();
    let mut mux=addr.connect(0).await?;
    let device=mux.get_devices().await?.into_iter().find(|d|d.udid.eq_ignore_ascii_case(udid)&&d.connection_type==Connection::Usb).ok_or_else(||report!("device_disconnected"))?;
    Ok(device.to_provider(addr,"RhineSign"))
}

async fn list()->Result<(),Report>{
    let mut mux=UsbmuxdAddr::default().connect(0).await?;
    let rows:Vec<Value>=mux.get_devices().await?.into_iter().filter(|d|d.connection_type==Connection::Usb).map(|d|json!({"udid":d.udid,"connection":"USB"})).collect();
    event("devices",json!(rows));Ok(())
}

async fn connect(udid:&str)->Result<(),Report>{
    let p=provider(udid).await?;
    let mut lock=LockdownClient::connect(&p).await?;
    let pairing=match p.get_pairing_file().await{
        Ok(record)=>record,
        Err(_)=>{
            event("stage",json!({"name":"请解锁 iPhone，并在手机上选择信任此电脑"}));
            let mut mux=UsbmuxdAddr::default().connect(0).await?;
            let buid=mux.get_buid().await?;
            let host=format!("RhineSign-{}",SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos());
            let record=lock.pair(host,buid,Some("RhineSign")).await?;
            mux.save_pair_record(&p.udid,record.clone().serialize()?).await?;
            record
        }
    };
    lock.start_session(&pairing).await?;
    let name=lock.get_value(Some("DeviceName"),None).await?.as_string().unwrap_or("iPhone").to_owned();
    let version=lock.get_value(Some("ProductVersion"),None).await?.as_string().unwrap_or("").to_owned();
    event("connected",json!({"udid":p.udid,"name":name,"version":version}));Ok(())
}

fn validate_package(path:&Path,udid:&str)->Result<(),Report>{
    if !valid_udid(udid)||!path.is_file()||path.extension().and_then(|s|s.to_str()).is_none_or(|s|!s.eq_ignore_ascii_case("ipa")){bail!("invalid_install_request");}
    let mut z=zip::ZipArchive::new(fs::File::open(path)?)?;
    let mut mains=Vec::new();let mut names=std::collections::HashSet::new();
    for i in 0..z.len(){let f=z.by_index(i)?;if f.enclosed_name().is_none()||!names.insert(f.name().to_owned()){bail!("invalid_install_archive");}
        let p:Vec<_>=f.name().split('/').collect();if p.len()==3&&p[0]=="Payload"&&p[1].ends_with(".app")&&p[2]=="Info.plist"{mains.push(p[1].to_owned());}}
    if mains.len()!=1{bail!("invalid_install_archive");}
    let prefix=format!("Payload/{}/",mains[0]);
    if let Ok(mut profile)=z.by_name(&(prefix+"embedded.mobileprovision")){
        if profile.size()>8*1024*1024{bail!("invalid_install_archive");}
        let mut bytes=Vec::new();profile.read_to_end(&mut bytes)?;
        if let Some(start)=bytes.windows(5).position(|v|v==b"<?xml"){
            if let Some(end)=bytes[start..].windows(8).position(|v|v==b"</plist>"){
                let value=plist::Value::from_reader_xml(&bytes[start..start+end+8])?;
                if let Some(d)=value.as_dictionary(){
                    if d.get("ExpirationDate").and_then(plist::Value::as_date).is_some_and(|v|SystemTime::from(v)<=SystemTime::now()){bail!("install_profile_expired");}
                    if let Some(devices)=d.get("ProvisionedDevices").and_then(plist::Value::as_array){if !devices.iter().any(|v|v.as_string().is_some_and(|s|s.eq_ignore_ascii_case(udid))){bail!("install_wrong_device");}}
                }
            }
        }
    }
    Ok(())
}

async fn install(request:&Request)->Result<(),Report>{
    if !request.confirmed{bail!("install_not_confirmed");}
    let path=request.ipa.as_ref().ok_or_else(||report!("invalid_install_request"))?.canonicalize()?;
    validate_package(&path,&request.udid)?;
    let p=provider(&request.udid).await?;
    let mut afc=AfcClient::connect(&p).await?;
    let staging=format!("PublicStaging/RhineSign-{}-{}.ipa",std::process::id(),SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos());
    // Use one bounded buffer, independent of the IPA's size. Never extract or
    // read the whole package into RAM, and only remove this exact staging file.
    let operation=async {
        let mut src=fs::File::open(&path)?;let total=src.metadata()?.len();let mut sent=0u64;
        let mut file=afc.open(&staging,AfcFopenMode::WrOnly).await?;
        let mut buffer=vec![0u8;1024*1024];
        event("stage",json!({"name":"正在通过 USB 传输 IPA"}));
        let upload=async {
            loop{let n=src.read(&mut buffer)?;if n==0{break;}file.write_entire(&buffer[..n]).await?;sent+=n as u64;event("progress",json!({"value":(sent as f64/total.max(1)as f64*70.0).min(70.0)}));}
            if sent!=total||src.metadata()?.len()!=total{bail!("install_source_changed");}Ok::<(),Report>(())
        }.await;
        let close=file.close().await;upload?;close?;
        event("stage",json!({"name":"正在等待 iPhone 完成安装"}));
        let mut ip=InstallationProxyClient::connect(&p).await?;
        let mut options=plist::Dictionary::new();options.insert("PackageType".into(),"Developer".into());
        ip.install_with_callback(staging.clone(),Some(plist::Value::Dictionary(options)),async |(percent,_)|{event("progress",json!({"value":70.0+percent as f64*0.3}));},()).await?;
        event("installed",json!({"path":path,"udid":p.udid}));Ok::<(),Report>(())
    }.await;
    let _=afc.remove(&staging).await;
    operation
}

pub(crate) fn dispatch(command:&str)->Result<(),Report>{
    let _=rustls::crypto::ring::default_provider().install_default();
    let rt=tokio::runtime::Runtime::new()?;
    if command=="--devices"{return rt.block_on(async{tokio::time::timeout(Duration::from_secs(12),list()).await.map_err(|_|report!("device_timeout"))?});}
    let request:Request=serde_json::from_str(&read_line()?)?;
    if command=="--connect-device"{return rt.block_on(async{tokio::time::timeout(Duration::from_secs(90),connect(&request.udid)).await.map_err(|_|report!("device_timeout"))?});}
    if command=="--install"{return rt.block_on(async{tokio::time::timeout(Duration::from_secs(60*30),install(&request)).await.map_err(|_|report!("device_timeout"))?});}
    bail!("invalid_install_request")
}

#[cfg(test)]mod tests{
    use super::*;
    #[test]fn install_requires_exact_request(){assert!(serde_json::from_str::<Request>(r#"{"udid":"bad","command":"delete"}"#).is_err());assert!(validate_package(Path::new("missing.ipa"),"bad").is_err());}
    #[test]fn no_device_zero_confirm(){let r=Request{udid:"bad".into(),ipa:None,confirmed:false};let rt=tokio::runtime::Runtime::new().unwrap();assert!(rt.block_on(install(&r)).is_err());}
}
