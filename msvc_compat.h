#pragma once
#if defined(_MSC_VER)
#include <intrin.h>
static __inline int __builtin_ctz(unsigned int x) {
    unsigned long idx;
    _BitScanForward(&idx, x);
    return (int)idx;
}
#endif