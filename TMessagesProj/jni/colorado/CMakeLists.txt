add_library(colorado STATIC
        colorado/cert.cpp
        colorado/colorado.cpp
        colorado/utils.cpp
)
target_include_directories(colorado PUBLIC colorado/)
target_compile_options(colorado PUBLIC -Oz -fvisibility=hidden)
target_include_directories(colorado PUBLIC integrity)

# Personal builds retain signature checking against their own signing certificate.
if(DEFINED NEKO_CERT_HASH OR DEFINED NEKO_CERT_SIZE OR DEFINED NEKO_PACKAGE_NAME)
    if(NOT DEFINED NEKO_CERT_HASH OR NOT DEFINED NEKO_CERT_SIZE OR NOT DEFINED NEKO_PACKAGE_NAME)
        message(FATAL_ERROR "Personal signature configuration requires package, certificate CRC and size")
    endif()
    target_compile_definitions(colorado PRIVATE
            PACKAGE_NAME="${NEKO_PACKAGE_NAME}"
            CERT_HASH=${NEKO_CERT_HASH}
            CERT_SIZE=${NEKO_CERT_SIZE})
endif()
