#!/usr/bin/env python3
"""Run the production native startup guard against a signed APK and a tampered copy.

The test substitutes only the APK descriptor path and records kill() requests.
Certificate extraction, CRC comparison and the reject path are production code.
"""
import argparse
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import zlib

p=argparse.ArgumentParser()
p.add_argument('apk',type=Path)
p.add_argument('--certificate',type=Path,required=True)
p.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1])
a=p.parse_args()
cert=a.certificate.read_bytes()
root=a.source.resolve()

with tempfile.TemporaryDirectory() as td:
 t=Path(td)
 (t/'colorado').symlink_to(root/'TMessagesProj/jni/colorado',target_is_directory=True)
 (t/'android').mkdir()
 (t/'android/log.h').write_text('#pragma once\n')
 (t/'probe.cpp').write_text(r'''
#include <cstdio>
#include <cstring>
#include <string>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <zlib.h>
#include "colorado.h"
static std::string fixture;
static int requestedSignal;
extern "C" ssize_t __real_readlinkat(int, const char*, char*, size_t);
extern "C" ssize_t __wrap_readlinkat(int dir, const char *name, char *out, size_t size) {
    ssize_t n = __real_readlinkat(dir, name, out, size);
    if (n > 0 && std::string(out, n) == fixture) {
        const std::string installed = "/data/app/fixture/tw.nekomimi.nekogram.personal-fixture/base.apk";
        if (installed.size() > size) return -1;
        memcpy(out, installed.data(), installed.size());
        return installed.size();
    }
    return n;
}
extern "C" int __wrap_kill(pid_t, int signal) { requestedSignal = signal; return 0; }
extern std::string read_certificate(int);
int main(int argc, char **argv) {
    if (argc != 2) return 64;
    fixture = argv[1];
    int fd = open(fixture.c_str(), O_RDONLY);
    if (fd < 0) return 65;
    auto cert = read_certificate(fd);
    printf("certificate_size=%zu certificate_crc32=0x%08lx\n", cert.size(), crc32(0, (const unsigned char*)cert.data(), cert.size()));
    bool result = check_signature();
    printf("check_signature=%s requested_signal=%d\n", result ? "true" : "false", requestedSignal);
    close(fd);
    return result ? 0 : 2;
}
''')
 # Include the actual project's CMake definitions, so the test also checks that
 # the configured certificate/package reaches the production compilation unit.
 (t/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.16)
project(StartupGuard LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
add_compile_options("SHELL:-include signal.h" "SHELL:-include string_view" "SHELL:-include cstring" "SHELL:-include cstdint" -DLOG_DISABLED=)
include_directories("${CMAKE_SOURCE_DIR}")
include("${NEKO_SOURCE}/TMessagesProj/jni/colorado/CMakeLists.txt")
add_executable(probe probe.cpp)
target_include_directories(probe PRIVATE "${NEKO_SOURCE}/TMessagesProj/jni/colorado")
target_link_libraries(probe PRIVATE colorado z)
target_link_options(probe PRIVATE -Wl,--wrap=readlinkat -Wl,--wrap=kill)
''')
 subprocess.run(['cmake','-S',str(t),'-B',str(t/'build'),'-DCMAKE_BUILD_TYPE=Release',
  '-DNEKO_SOURCE='+str(root),'-DNEKO_PACKAGE_NAME=tw.nekomimi.nekogram.personal',
  '-DNEKO_CERT_HASH=0x%08x'%zlib.crc32(cert),'-DNEKO_CERT_SIZE='+str(len(cert))],check=True,stdout=subprocess.PIPE)
 subprocess.run(['cmake','--build',str(t/'build'),'--parallel','2'],check=True,stdout=subprocess.PIPE)
 good=subprocess.run([str(t/'build/probe'),str(a.apk.resolve())],capture_output=True,text=True)
 print('SIGNED_APK\n'+good.stdout+'exit='+str(good.returncode))
 assert good.returncode==0 and 'requested_signal=0' in good.stdout, 'Startup signature check rejects the configured signing key'
 data=a.apk.read_bytes()
 assert cert in data,'Certificate not found in APK'
 bad=t/'tampered.apk';bad.write_bytes(data.replace(cert,bytes([cert[0]^1])+cert[1:]))
 rejected=subprocess.run([str(t/'build/probe'),str(bad)],capture_output=True,text=True)
 print('TAMPERED_CERTIFICATE\n'+rejected.stdout+'exit='+str(rejected.returncode))
 assert rejected.returncode==2 and 'requested_signal=9' in rejected.stdout, 'Modified certificate must be rejected'
 print('PASS configured personal certificate accepted; tampered certificate rejected by production startup guard')
