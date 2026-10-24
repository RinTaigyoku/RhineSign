//! Structural nested-signature guard. Not an Apple trust-chain/runtime verdict.
use std::{path::Path,fs};
use rootcause::prelude::*;
fn u32_at(data:&[u8],p:usize,be:bool)->Result<u32,Report>{let b:[u8;4]=data.get(p..p+4).ok_or_else(||report!("signature_bounds"))?.try_into()?;Ok(if be{u32::from_be_bytes(b)}else{u32::from_le_bytes(b)})}
fn u64_at(data:&[u8],p:usize)->Result<u64,Report>{Ok(u64::from_be_bytes(data.get(p..p+8).ok_or_else(||report!("signature_bounds"))?.try_into()?))}
pub(crate) fn check(data:&[u8],team:&str,require_cms:bool)->Result<usize,Report>{
    let magic=data.get(..4).ok_or_else(||report!("signature_bounds"))?;
    if magic==[0xca,0xfe,0xba,0xbe] || magic==[0xca,0xfe,0xba,0xbf]{
        let wide=magic[3]==0xbf;let count=u32_at(data,4,true)? as usize;if count==0||count>32{bail!("signature_fat_count");}
        let mut total=0;
        for i in 0..count {let p=8+i*if wide{32}else{20};let off=if wide{u64_at(data,p+8)?}else{u32_at(data,p+8,true)? as u64};let size=if wide{u64_at(data,p+16)?}else{u32_at(data,p+12,true)? as u64};let end=off.checked_add(size).ok_or_else(||report!("signature_bounds"))?;if off<(8+count*if wide{32}else{20})as u64||size<28||end>data.len()as u64{bail!("signature_bounds");}let slice=&data[off as usize..end as usize];if slice.get(..4)!=Some(&[0xcf,0xfa,0xed,0xfe])&&slice.get(..4)!=Some(&[0xce,0xfa,0xed,0xfe]){bail!("signature_unsupported_macho");}total+=check(slice,team,require_cms)?;}
        return Ok(total);
    }
    if magic!=[0xcf,0xfa,0xed,0xfe]&&magic!=[0xce,0xfa,0xed,0xfe]{bail!("signature_unsupported_macho");}
    let executable=u32_at(data,12,false)?==2;let count=u32_at(data,16,false)? as usize;let commands=u32_at(data,20,false)? as usize;
    let mut p=if magic[0]==0xcf{32}else{28};let end=p+commands;if end>data.len()||count>4096{bail!("signature_bounds");}let mut signature=None;
    for _ in 0..count {let cmd=u32_at(data,p,false)?;let size=u32_at(data,p+4,false)? as usize;if size<8||p+size>end{bail!("signature_bounds");}if cmd==0x1d{let off=u32_at(data,p+8,false)? as usize;let len=u32_at(data,p+12,false)? as usize;signature=Some(data.get(off..off+len).ok_or_else(||report!("signature_bounds"))?);}p+=size;}
    let blob=signature.ok_or_else(||report!("signature_missing"))?;
    if u32_at(blob,0,true)?!=0xfade0cc0{bail!("signature_bad_superblob");}let len=u32_at(blob,4,true)? as usize;let count=u32_at(blob,8,true)? as usize;if len>blob.len()||count>32{bail!("signature_bounds");}
    let mut xml=false;let mut der=false;let mut cms=false;let mut directories=0;let mut slots=std::collections::HashSet::new();
    for i in 0..count {
        let slot=u32_at(blob,12+i*8,true)?;if !slots.insert(slot){bail!("signature_duplicate_slot");}let off=u32_at(blob,16+i*8,true)? as usize;let size=u32_at(blob,off+4,true)? as usize;if size<8||off+size>len{bail!("signature_bounds");}let b=&blob[off..off+size];
        if slot==5{xml=true;}if slot==7{der=true;}if slot==0x10000{cms=u32_at(b,0,true)?==0xfade0b01&&size>8;}
        if slot==0||(0x1000..0x1005).contains(&slot){
            directories+=1;if u32_at(b,0,true)?!=0xfade0c02||u32_at(b,8,true)?<0x20400{bail!("signature_bad_directory");}
            let teamoff=u32_at(b,48,true)? as usize;if teamoff==0{bail!("signature_team_mismatch");}let value=b.get(teamoff..).ok_or_else(||report!("signature_bounds"))?;let stop=value.iter().position(|x|*x==0).ok_or_else(||report!("signature_bounds"))?;if &value[..stop]!=team.as_bytes(){bail!("signature_team_mismatch");}
            if !executable {
                let n=u32_at(b,24,true)? as usize;let hashes=u32_at(b,16,true)? as usize;let width=*b.get(36).ok_or_else(||report!("signature_bounds"))? as usize;
                for slot in [5,7]{if n>=slot {let back=slot*width;let begin=hashes.checked_sub(back).ok_or_else(||report!("signature_bounds"))?;if b.get(begin..begin+width).ok_or_else(||report!("signature_bounds"))?.iter().any(|x|*x!=0){bail!("nested_permissions_present");}}}
            }
        }
    }
    if directories==0||(require_cms&&!cms){bail!("signature_missing");}
    if !executable&&(xml||der){bail!("nested_permissions_present");}
    if executable&&xml&&!der{bail!("signature_missing_der");}
    Ok(1)
}
pub(crate) fn bundle(root:&Path,executable:&str,team:&str)->Result<usize,Report>{
    let mut count=check(&fs::read(root.join(executable))?,team,true)?;
    for item in walkdir::WalkDir::new(root){let item=item?;if !item.file_type().is_file(){continue;}let path=item.path();let dylib=path.extension().and_then(|s|s.to_str())==Some("dylib");let framework=path.parent().is_some_and(|p|p.extension().and_then(|s|s.to_str())==Some("framework")&&p.file_stem()==path.file_name());if dylib||framework {count+=check(&fs::read(path)?,team,true)?;}}
    Ok(count)
}
