// Minimal port of luka-dev/qnx65-armv7-toolchain's gcc/port/qnx-os_defines.h
// (the GCC 8.5 variant) size_t/ptrdiff_t fix. The GCC 4.9 toolchain image lacks
// the #undef of GCC stddef's empty __SIZE_T / __PTRDIFF_T guards, so QNX's
// sys/mman.h ("typedef __SIZE_T size_t;") fails to compile. Include this first
// with -include toolchain/qnx-preamble.h when building for QNX 6.5.
#include <stddef.h>
typedef __SIZE_TYPE__ size_t;
typedef __PTRDIFF_TYPE__ ptrdiff_t;
#undef __SIZE_T
#undef __PTRDIFF_T
#undef __WCHAR_T
#ifndef _QNX_SOURCE
#define _QNX_SOURCE 1
#endif
#ifndef _HAS_C9X
#define _HAS_C9X 1
#endif
