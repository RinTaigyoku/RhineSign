mod tests {
    use super::*;
    use isideload::SideloadError;
    fn synthetic_macho(executable:bool)->Vec<u8>{
        fn put(d:&mut[u8],p:usize,v:u32){d[p..p+4].copy_from_slice(&v.to_le_bytes());}
        fn long(d:&mut[u8],p:usize,v:u64){d[p..p+8].copy_from_slice(&v.to_le_bytes());}
        let mut d=vec![0;512];put(&mut d,0,0xfeedfacf);put(&mut d,4,0x100000c);put(&mut d,12,if executable{2}else{6});put(&mut d,16,3);put(&mut d,20,160);
        for (p,name,off,size,va)in[(32,"__TEXT",0,512,0x100000000),(104,"__LINKEDIT",512,0,0x100004000)]{
            put(&mut d,p,25);put(&mut d,p+4,72);d[p+8..p+8+name.len()].copy_from_slice(name.as_bytes());long(&mut d,p+24,va);long(&mut d,p+32,16384);long(&mut d,p+40,off);long(&mut d,p+48,size);put(&mut d,p+56,7);put(&mut d,p+60,if off==0{5}else{1});
        }
        put(&mut d,176,0x1d);put(&mut d,180,16);put(&mut d,184,512);d
    }
    #[test] fn real_generated_nested_signature_omits_permissions(){
        use apple_codesign_quick::{MachOSigningConfig,sign_macho_data};
        let mut entitlements=plist::Dictionary::new();entitlements.insert("get-task-allow".into(),plist::Value::Boolean(true));
        let config=MachOSigningConfig::new("org.example.synthetic","TESTTEAM",&entitlements,None);
        for executable in [false,true]{
            let b=sign_macho_data(std::path::Path::new("synthetic"),&synthetic_macho(executable),&config).unwrap();
            assert_eq!(signature_guard::check(&b,"TESTTEAM",false).unwrap(),1);
            assert!(signature_guard::check(&b,"OTHERTEAM",false).is_err());assert!(signature_guard::check(&b,"TESTTEAM",true).is_err());
            let off=u32::from_le_bytes(b[184..188].try_into().unwrap())as usize;let blob=&b[off..];let count=u32::from_be_bytes(blob[8..12].try_into().unwrap())as usize;
            let slots:Vec<_>=(0..count).map(|i|u32::from_be_bytes(blob[12+i*8..16+i*8].try_into().unwrap())).collect();
            assert_eq!(slots.contains(&5),executable);assert_eq!(slots.contains(&7),executable);
        }
    }
    #[test] fn signature_guard_rejects_bad_bounds_and_recursive_fat(){
        for n in 0..40 {assert!(signature_guard::check(&vec![0;n],"TESTTEAM",false).is_err());}
        let mut b=vec![0;32];b[..4].copy_from_slice(&[0xca,0xfe,0xba,0xbe]);b[4..8].copy_from_slice(&1u32.to_be_bytes());b[20..24].copy_from_slice(&32u32.to_be_bytes());assert!(signature_guard::check(&b,"TESTTEAM",false).is_err());
    }
    #[test] fn replacement_requires_exact_choice_and_confirmation(){
        let certs:Vec<DevelopmentCertificate>=serde_json::from_value(json!([{"serialNumber":"EXACT-ONE"}])).unwrap();
        assert!(approved_replacement(&json!({"action":"cancel"}),&certs).unwrap().is_none());
        for reply in [json!({}),json!({"serial":"EXACT-ONE"}),json!({"confirmed":false,"serial":"EXACT-ONE"}),json!({"confirmed":true,"serial":"OTHER"}),json!({"confirmed":true,"serial":""})] {
            assert!(approved_replacement(&reply,&certs).is_err());
        }
        assert_eq!(approved_replacement(&json!({"confirmed":true,"serial":"EXACT-ONE"}),&certs).unwrap(),Some(vec!["EXACT-ONE".into()]));
        assert!(approved_replacement(&json!({"confirmed":true,"serial":"EXACT-ONE"}),&[]).is_err());
    }
    #[test] fn input_validation(){self_test().unwrap();}
    #[test] fn errors_do_not_echo_apple_message(){let e:Report=report!(SideloadError::AuthWithMessage(-22411,"SECRET_SESSION".into())).into();let s=safe_error(&e);assert!(s.contains("-22411"));assert!(!s.contains("SECRET"));}
    #[test] fn fixed_failure_categories(){let e:Report=report!("auth_timeout").into();assert!(safe_error(&e).contains("180"));let e:Report=report!("Failed to get anisette client info").into();assert!(safe_error(&e).contains("辅助服务"));}
    #[test] fn selected_ipa_supplies_bundle_id(){
        let root=std::env::temp_dir().join(format!("rs-bundle-test-{}",std::process::id()));fs::create_dir_all(root.join("tree/Payload/other.app")).unwrap();
        fs::write(root.join("tree/Payload/other.app/Info.plist"),b"<?xml version=\"1.0\"?><plist version=\"1.0\"><dict><key>CFBundleIdentifier</key><string>org.example.another</string></dict></plist>").unwrap();
        pack_signed(&root.join("tree"),&root.join("another.ipa")).unwrap();assert_eq!(original_bundle(&root.join("another.ipa")).unwrap(),"org.example.another");fs::remove_dir_all(root).unwrap();
    }
    #[test] fn existing_output_is_preserved(){let p=std::env::temp_dir().join(format!("rs-no-overwrite-{}",std::process::id()));fs::write(&p,b"original").unwrap();assert!(write_new(&p,b"replacement").is_err());assert_eq!(fs::read(&p).unwrap(),b"original");fs::remove_file(p).unwrap();}
    #[test] fn archive_resources_are_checked(){
        let root=std::env::temp_dir().join(format!("rs-zip-test-{}",std::process::id()));fs::create_dir_all(root.join("tree/Payload/test.app/Frameworks")).unwrap();
        fs::write(root.join("tree/Payload/test.app/assets.bundle"),b"unchanged resource").unwrap();fs::write(root.join("tree/Payload/test.app/Frameworks/ExamplePlugin.dylib"),b"test-only").unwrap();
        let info=b"<?xml version=\"1.0\"?><plist version=\"1.0\"><dict><key>LSSupportsGameMode</key><true/></dict></plist>";
        fs::write(root.join("tree/Payload/test.app/Info.plist"),info).unwrap();
        pack_signed(&root.join("tree"),&root.join("original.ipa")).unwrap();pack_signed(&root.join("tree"),&root.join("signed.ipa")).unwrap();verify_resources(&root.join("original.ipa"),&root.join("signed.ipa")).unwrap();
        fs::write(root.join("tree/Payload/test.app/Info.plist"),b"<?xml version=\"1.0\"?><plist version=\"1.0\"><dict><key>LSSupportsGameMode</key><false/></dict></plist>").unwrap();pack_signed(&root.join("tree"),&root.join("bad-info.ipa")).unwrap();assert!(verify_resources(&root.join("original.ipa"),&root.join("bad-info.ipa")).is_err());fs::write(root.join("tree/Payload/test.app/Info.plist"),info).unwrap();
        fs::write(root.join("tree/Payload/test.app/assets.bundle"),b"incorrect changed resource").unwrap();pack_signed(&root.join("tree"),&root.join("bad.ipa")).unwrap();assert!(verify_resources(&root.join("original.ipa"),&root.join("bad.ipa")).is_err());
        fs::remove_dir_all(root).unwrap();
    }
    #[test] fn profile_association_and_expiry(){
        use plist::Value;
        let mut d=plist::Dictionary::new();let mut e=plist::Dictionary::new();e.insert("application-identifier".into(),Value::String("TEAM.com.test.app".into()));
        d.insert("Entitlements".into(),Value::Dictionary(e));d.insert("TeamIdentifier".into(),Value::Array(vec![Value::String("TEAM".into())]));
        d.insert("ProvisionedDevices".into(),Value::Array(vec![Value::String("DEVICE".into())]));d.insert("DeveloperCertificates".into(),Value::Array(vec![Value::Data(vec![1,2,3])]));
        d.insert("ExpirationDate".into(),Value::Date((SystemTime::now()+Duration::from_secs(3600)).into()));
        assert!(profile_matches(&d,"TEAM","com.test.app","DEVICE",&[1,2,3]));
        assert!(!profile_matches(&d,"TEAM","com.test.other","DEVICE",&[1,2,3]));assert!(!profile_matches(&d,"TEAM","com.test.app","OTHER",&[1,2,3]));
        assert!(!profile_matches(&d,"TEAM","com.test.app","DEVICE",&[9]));assert!(!profile_matches(&d,"OTHER","com.test.app","DEVICE",&[1,2,3]));
        let mut raw=b"FAKE-CMS".to_vec();Value::Dictionary(d.clone()).to_writer_xml(&mut raw).unwrap();raw.extend_from_slice(b"FAKE-TRAILER");
        check_downloaded_profile(&raw,"TEAM","com.test.app","DEVICE",&[1,2,3]).unwrap();
        d.insert("ExpirationDate".into(),Value::Date((SystemTime::now()-Duration::from_secs(1)).into()));assert!(!profile_matches(&d,"TEAM","com.test.app","DEVICE",&[1,2,3]));
        assert!(check_downloaded_profile(b"bad","TEAM","com.test.app","DEVICE",&[1,2,3]).is_err());
    }
}
