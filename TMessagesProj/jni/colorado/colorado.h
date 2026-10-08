#include <stdbool.h>

#ifdef NDEBUG
#define LOG_DISABLED
#endif
#ifndef PACKAGE_NAME
#define PACKAGE_NAME "tw.nekomimi.nekogram"_iobfs.c_str()
#endif
#ifndef CERT_HASH
#define CERT_HASH 0x693cc8c5
#endif
#ifndef CERT_SIZE
#define CERT_SIZE 0x2d7
#endif

#ifdef __cplusplus
extern "C" {
#endif

bool check_signature();

#ifdef __cplusplus
}
#endif
