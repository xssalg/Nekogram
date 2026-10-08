#!/usr/bin/env python3
"""Compile production ProxySettings with minimal Android adapters for host-side tests."""
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
stubs = {
 'androidx/annotation/NonNull.java': 'package androidx.annotation; public @interface NonNull {}',
 'android/text/TextUtils.java': 'package android.text; public class TextUtils {public static boolean isEmpty(CharSequence s){return s==null || s.length()==0;}}',
 'android/content/SharedPreferences.java': '''package android.content;
public interface SharedPreferences {
 String getString(String key,String fallback); int getInt(String key,int fallback);
 interface Editor { Editor putInt(String key,int v); Editor putString(String key,String v); Editor remove(String key); }
}''',
 'android/util/Base64.java': '''package android.util; public class Base64 {
 public static final int URL_SAFE=8,NO_WRAP=2,NO_PADDING=1;
 public static byte[] decode(String s,int f){return java.util.Base64.getUrlDecoder().decode(s);}
 public static String encodeToString(byte[] b,int f){return java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(b);}
}''',
 'android/net/Uri.java': '''package android.net;
public class Uri { private final java.net.URI u; private Uri(String s){u=java.net.URI.create(s);}
 public static Uri parse(String s){return new Uri(s);} public String getScheme(){return u.getScheme();}
 public String getHost(){return u.getHost();} public String getPath(){return u.getPath();}
 public String toString(){return u.toString();} public String getQueryParameter(String key){
 String q=u.getRawQuery(); if(q==null)return null; for(String p:q.split("&")){String[] kv=p.split("=",2);
 if(kv[0].equals(key))return java.net.URLDecoder.decode(kv.length>1?kv[1]:"", java.nio.charset.StandardCharsets.UTF_8);}return null;}
}''',
 'org/telegram/messenger/AndroidUtilities.java': '''package org.telegram.messenger;
public class AndroidUtilities {public static boolean checkHostForPunycode(String s){return s!=null && !java.nio.charset.StandardCharsets.US_ASCII.newEncoder().canEncode(s);}}''',
 'SettingsTest.java': '''import org.telegram.utils.proxy.ProxySettings;
import android.content.SharedPreferences;
import android.net.Uri;
import java.util.HashMap;
public class SettingsTest {
 static class Preferences implements SharedPreferences, SharedPreferences.Editor {
  HashMap<String,Object> values=new HashMap<>();
  public String getString(String k,String d){return (String)values.getOrDefault(k,d);}
  public int getInt(String k,int d){return (Integer)values.getOrDefault(k,d);}
  public Preferences putInt(String k,int v){values.put(k,v);return this;}
  public Preferences putString(String k,String v){values.put(k,v);return this;}
  public Preferences remove(String k){values.remove(k);return this;}
 }
 static void check(boolean b){if(!b)throw new AssertionError();}
 public static void main(String[] args) {
  ProxySettings.Type http=ProxySettings.Type.HTTP;
  check(ProxySettings.intToType(0)==ProxySettings.Type.SOCKS5);
  check(ProxySettings.intToType(1)==ProxySettings.Type.MTPROTO);
  check(ProxySettings.intToType(2)==ProxySettings.Type.WEB);
  check(ProxySettings.intToType(3)==http && ProxySettings.typeToInt(http)==3);
  ProxySettings s=ProxySettings.builder().setType(http).setAddress("proxy.example").setPort(8080).setUser("a b@x").setPassword("p&+/:密").setSecret("ignored").build();
  check(s.isValid() && s.getSecret().isEmpty());
  Preferences prefs=new Preferences(); prefs.putString("proxy_secret","old secret");s.toSharedPreferences(prefs);
  check(ProxySettings.fromSharedPreferences(prefs).equals(s)); check(!prefs.values.containsKey("proxy_secret"));
  check(ProxySettings.fromUri(Uri.parse(s.getLink())).equals(s));
  ProxySettings v6=ProxySettings.builder().setType(http).setAddress("2001:db8::1").setPort(3128).build();
  check(ProxySettings.fromUri(Uri.parse(v6.getLink())).equals(v6));
  check(!ProxySettings.builder().setType(http).setAddress("host").setPort(65536).build().isValid());
  check(!ProxySettings.builder().setType(http).setAddress("host").setPort(8080).setUser("bad:user").build().isValid());
  check(ProxySettings.fromUri(Uri.parse("tg://socks?server=host&port=1080&user=u&pass=p")).getType()==ProxySettings.Type.SOCKS5);
  check(ProxySettings.fromUri(Uri.parse("tg://proxy?server=host&port=443&secret=abc")).getType()==ProxySettings.Type.MTPROTO);
  check(ProxySettings.fromUri(Uri.parse("tg://webproxy?server=host&secret=0123456789abcdef0123456789abcdef")).getType()==ProxySettings.Type.WEB);
  System.out.println("PASS type IDs, HTTP settings persistence, URI round trips, credential escaping, IPv6, invalid settings, legacy proxy types");
 }
}'''
}
with tempfile.TemporaryDirectory() as d:
 tmp=Path(d)
 for name,code in stubs.items():
  f=tmp/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(code)
 source=ROOT/'TMessagesProj/src/main/java/org/telegram/utils/proxy/ProxySettings.java'
 subprocess.run(['javac','-d',str(tmp),str(source),*[str(tmp/n) for n in stubs]],check=True)
 subprocess.run(['java','-cp',str(tmp),'SettingsTest'],check=True)
