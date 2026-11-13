/*
 * Very simple but very effective user-space memory tester.
 * Originally by Simon Kirby <sim@stormix.com> <sim@neato.org>
 * Version 2 by Charles Cazabon <charlesc-memtester@pyropus.ca>
 * Version 3 not publicly released.
 * Version 4 rewrite:
 * Copyright (C) 2004-2020 Charles Cazabon <charlesc-memtester@pyropus.ca>
 * Licensed under the terms of the GNU General Public License version 2 (only).
 * See the file COPYING for details.
 *
 * This file contains the functions for the actual tests, called from the
 * main routine in memtester.c.  See other comments in that file.
 *
 */

#include <sys/types.h>
#include <stdio.h>
#include <stdlib.h>
#include <limits.h>
#include <stdint.h>
#include <unistd.h>

#include "types.h"
#include "sizes.h"
#include "memtester.h"
#include "output.h"

#define ONE 0x00000001L
//ba
uintptr_t inject_bufa_start = 0;    // bufa 起始虚拟地址
size_t inject_pagesize = 0;         // 页面大小
ssize_t inject_page_rel = -1;       // 相对 bufa 的注入页号（-1 表示不注入）
int inject_kind = 0;             // 注入类型
int inject_once = 1;                // 注入后是否只注入一次
uintptr_t rampage_test_base = 0;
struct rampage_failure rampage_failures[2];
size_t rampage_failure_count = 0;
size_t rampage_injection_offset = SIZE_MAX;
FILE *rampage_result = NULL;
ul *rampage_expected = NULL;
size_t rampage_expected_count = 0;
static int rampage_expected_valid = 0;

static void rampage_expect(size_t index, ul value) {
    if (rampage_expected && index < rampage_expected_count) {
        rampage_expected[index] = value;
        rampage_expected_valid = 1;
    }
}

static size_t byte_offset(ulv *word, ul expected, ul observed) {
    const unsigned char *a = (const unsigned char *)&expected;
    const unsigned char *b = (const unsigned char *)&observed;
    size_t byte = 0;

    while (byte < sizeof(ul) - 1 && a[byte] == b[byte] && expected != observed)
        byte++;
    return (uintptr_t)word - rampage_test_base + byte;
}

static void record_failure(ulv *word, char side, ul expected, ul observed) {
    if (rampage_test_base) {
        rampage_failures[rampage_failure_count++] = (struct rampage_failure) {
            byte_offset(word, expected, observed), side, expected, observed
        };
    }
}

static int injection_targets(ulv *bufa, size_t count, int kind) {
    uintptr_t start = (uintptr_t)bufa;
    uintptr_t end = (uintptr_t)(bufa + count);
    uintptr_t target;

    if ((rampage_test_base && !inject_once) || inject_kind != kind || inject_page_rel < 0 ||
        !inject_pagesize || (size_t)inject_page_rel > (UINTPTR_MAX - inject_bufa_start) / inject_pagesize)
        return 0;
    target = inject_bufa_start + (size_t)inject_page_rel * inject_pagesize;
    return target < end && (target >= start || start - target < inject_pagesize);
}

/* Flip the original low bit in each selected A-side word. */
static int rampage_inject(ulv *bufa, size_t count, int kind) {
    size_t i;

    if (!injection_targets(bufa, count, kind))
        return 0;
    if (rampage_test_base)
        inject_once = 0;
    for (i = 0; i < count; i++) {
        uintptr_t address = (uintptr_t)&bufa[i];
        ul before, intended, observed;

        if (address < inject_bufa_start ||
            (address - inject_bufa_start) / inject_pagesize != (size_t)inject_page_rel)
            continue;
        if (!rampage_test_base) {
            bufa[i] ^= 0x1;
            continue;
        }
        before = bufa[i];
        if (rampage_expected_valid && i < rampage_expected_count &&
            before != rampage_expected[i]) {
            record_failure(&bufa[i], 'A', rampage_expected[i], before);
            return -1;
        }
        intended = before ^ 0x1;
        bufa[i] = intended;
        observed = bufa[i];
        if (rampage_injection_offset == SIZE_MAX) {
            rampage_injection_offset = byte_offset(&bufa[i], before, observed);
            fprintf(stderr, "RAMPAGE_INJECTION kind=%d page=%zd offset=%zu before=%#lx after=%#lx\n",
                    kind, inject_page_rel, rampage_injection_offset, before, observed);
            if (rampage_result) {
                fprintf(rampage_result, "INJECT %d %zd %zu %lu %lu\n",
                        kind, inject_page_rel, rampage_injection_offset, before, observed);
                fflush(rampage_result);
            }
        }
        if (observed != intended) {
            record_failure(&bufa[i], 'A', intended, observed);
            return -1;
        }
    }
    return 0;
}

void rampage_reset_failure(void) {
    rampage_failure_count = 0;
    rampage_expected_valid = 0;
}

union {
    unsigned char bytes[UL_LEN/8];
    ul val;
} mword8;

union {
    unsigned short u16s[UL_LEN/16];
    ul val;
} mword16;

/* Function definitions. */

int compare_regions(ulv *bufa, ulv *bufb, size_t count) {
    int result = 0;
    size_t i;
    ulv *p1 = bufa;
    ulv *p2 = bufb;
    off_t physaddr;

    for (i = 0; i < count; i++, p1++, p2++) {
        ul a = *p1;
        ul b = *p2;

        if (rampage_expected_valid && i < rampage_expected_count) {
            ul expected = rampage_expected[i];

            if (a == expected && b == expected)
                continue;
            if (a != expected)
                record_failure(p1, 'A', expected, a);
            if (b != expected)
                record_failure(p2, 'B', expected, b);
            fprintf(stderr, "FAILURE: A=%#lx B=%#lx expected=%#lx at word offset %#zx.\n",
                    a, b, expected, i * sizeof(ul));
            return -1;
        }
        if (a != b) {
            if (use_phys) {
                physaddr = physaddrbase + (i * sizeof(ul));
                fprintf(stderr,
                        "FAILURE: 0x%08lx != 0x%08lx at physical address "
                        "0x%08lx.\n",
                        a, b, physaddr);
            } else {
                fprintf(stderr,
                        "FAILURE: 0x%08lx != 0x%08lx at offset 0x%08lx.\n",
                        a, b, (ul) (i * sizeof(ul)));
            }
            result = -1;
        }
    }
    return result;
}

static int compare_with_injection(ulv *bufa, ulv *bufb, size_t count, int kind) {
    if (rampage_test_base && injection_targets(bufa, count, kind) &&
        compare_regions(bufa, bufb, count))
        return -1;
    if (rampage_inject(bufa, count, kind))
        return -1;
    return compare_regions(bufa, bufb, count);
}

int test_stuck_address(ulv *bufa, size_t count) {
    ulv *p1 = bufa;
    unsigned int j;
    size_t i;
    off_t physaddr;

    out_test_start();
    for (j = 0; j < 16; j++) {
        p1 = (ulv *) bufa;
        out_test_setting(j);
        for (i = 0; i < count; i++) {
            ul expected = ((j + i) % 2) == 0 ? (ul)p1 : ~((ul)p1);
            rampage_expect(i, expected);
            *p1++ = expected;
        }
        if (rampage_inject(bufa, count, 1))
            return -1;
        out_test_testing(j);
        p1 = (ulv *) bufa;
        for (i = 0; i < count; i++, p1++) {
            ul expected = ((j + i) % 2) == 0 ? (ul)p1 : ~((ul)p1);
            ul observed = *p1;

            if (observed != expected) {
                record_failure(p1, 'A', expected, observed);
                if (use_phys) {
                    physaddr = physaddrbase + (i * sizeof(ul));
                    fprintf(stderr,
                            "FAILURE: possible bad address line at physical "
                            "address 0x%08lx.\n",
                            physaddr);
                } else {
                    fprintf(stderr,
                            "FAILURE: possible bad address line at offset "
                            "0x%08lx.\n",
                            (ul) (i * sizeof(ul)));
                }
                printf("Skipping to next test...\n");
                fflush(stdout);
                return -1;
            }
        }
    }
    out_test_end();
    return 0;
}

int test_random_value(ulv *bufa, ulv *bufb, size_t count) {
    ulv *p1 = bufa;
    ulv *p2 = bufb;
    size_t i;

    out_wheel_start();
    for (i = 0; i < count; i++) {
        ul expected = rand_ul();
        rampage_expect(i, expected);
        *p1++ = *p2++ = expected;
        out_wheel_advance(i);
    }
    out_wheel_end();
    return compare_regions(bufa, bufb, count);
}

int test_xor_comparison(ulv *bufa, ulv *bufb, size_t count) {
    ulv *p1 = bufa;
    ulv *p2 = bufb;
    size_t i;
    ul q = rand_ul();

    for (i = 0; i < count; i++) {
        *p1++ ^= q;
        *p2++ ^= q;
        rampage_expect(i, UL_ONEBITS ^ q);
    }
    return compare_with_injection(bufa, bufb, count, 2);
}

int test_sub_comparison(ulv *bufa, ulv *bufb, size_t count) {
    ulv *p1 = bufa;
    ulv *p2 = bufb;
    size_t i;
    ul q = rand_ul();

    for (i = 0; i < count; i++) {
        *p1++ -= q;
        *p2++ -= q;
        rampage_expect(i, UL_ONEBITS - q);
    }
    return compare_regions(bufa, bufb, count);
}

int test_mul_comparison(ulv *bufa, ulv *bufb, size_t count) {
    ulv *p1 = bufa;
    ulv *p2 = bufb;
    size_t i;
    ul q = rand_ul();

    for (i = 0; i < count; i++) {
        *p1++ *= q;
        *p2++ *= q;
        rampage_expect(i, UL_ONEBITS * q);
    }
    return compare_regions(bufa, bufb, count);
}

int test_div_comparison(ulv *bufa, ulv *bufb, size_t count) {
    ulv *p1 = bufa;
    ulv *p2 = bufb;
    size_t i;
    ul q = rand_ul();

    for (i = 0; i < count; i++) {
        if (!q) {
            q++;
        }
        *p1++ /= q;
        *p2++ /= q;
        rampage_expect(i, UL_ONEBITS / q);
    }
    return compare_regions(bufa, bufb, count);
}

int test_or_comparison(ulv *bufa, ulv *bufb, size_t count) {
    ulv *p1 = bufa;
    ulv *p2 = bufb;
    size_t i;
    ul q = rand_ul();

    for (i = 0; i < count; i++) {
        *p1++ |= q;
        *p2++ |= q;
        rampage_expect(i, UL_ONEBITS | q);
    }
    return compare_with_injection(bufa, bufb, count, 6);
}


int test_and_comparison(ulv *bufa, ulv *bufb, size_t count) {
    ulv *p1 = bufa;
    ulv *p2 = bufb;
    size_t i;
    ul q = rand_ul();

    for (i = 0; i < count; i++) {
        *p1++ &= q;
        *p2++ &= q;
        rampage_expect(i, UL_ONEBITS & q);
    }
    return compare_regions(bufa, bufb, count);
}

int test_seqinc_comparison(ulv *bufa, ulv *bufb, size_t count) {
    ulv *p1 = bufa;
    ulv *p2 = bufb;
    size_t i;
    ul q = rand_ul();

    for (i = 0; i < count; i++) {
        ul expected = i + q;
        rampage_expect(i, expected);
        *p1++ = *p2++ = expected;
    }
    return compare_regions(bufa, bufb, count);
}

int test_solidbits_comparison(ulv *bufa, ulv *bufb, size_t count) {
    ulv *p1 = bufa;
    ulv *p2 = bufb;
    unsigned int j;
    ul q;
    size_t i;

    out_test_start();
    for (j = 0; j < 64; j++) {
        q = (j % 2) == 0 ? UL_ONEBITS : 0;
        out_test_setting(j);
        p1 = (ulv *) bufa;
        p2 = (ulv *) bufb;
        for (i = 0; i < count; i++) {
            ul expected = (i % 2) == 0 ? q : ~q;
            rampage_expect(i, expected);
            *p1++ = *p2++ = expected;
        }
        out_test_testing(j);
        if (compare_with_injection(bufa, bufb, count, 3)) {
            return -1;
        }
    }
    out_test_end();
    return 0;
}

int test_checkerboard_comparison(ulv *bufa, ulv *bufb, size_t count) {
    ulv *p1 = bufa;
    ulv *p2 = bufb;
    unsigned int j;
    ul q;
    size_t i;

    out_test_start();
    for (j = 0; j < 64; j++) {
        q = (j % 2) == 0 ? CHECKERBOARD1 : CHECKERBOARD2;
        out_test_setting(j);
        p1 = (ulv *) bufa;
        p2 = (ulv *) bufb;
        for (i = 0; i < count; i++) {
            ul expected = (i % 2) == 0 ? q : ~q;
            rampage_expect(i, expected);
            *p1++ = *p2++ = expected;
        }
        out_test_testing(j);
        if (compare_with_injection(bufa, bufb, count, 4)) {
            return -1;
        }
    }
    out_test_end();
    return 0;
}

int test_blockseq_comparison(ulv *bufa, ulv *bufb, size_t count) {
    ulv *p1 = bufa;
    ulv *p2 = bufb;
    unsigned int j;
    size_t i;

    out_test_start();
    for (j = 0; j < 256; j++) {
        p1 = (ulv *) bufa;
        p2 = (ulv *) bufb;
        out_test_setting(j);
        for (i = 0; i < count; i++) {
            ul expected = (ul) UL_BYTE(j);
            rampage_expect(i, expected);
            *p1++ = *p2++ = expected;
        }
        out_test_testing(j);
        if (compare_regions(bufa, bufb, count)) {
            return -1;
        }
    }
    out_test_end();
    return 0;
}

int test_walkbits0_comparison(ulv *bufa, ulv *bufb, size_t count) {
    ulv *p1 = bufa;
    ulv *p2 = bufb;
    unsigned int j;
    size_t i;

    out_test_start();
    for (j = 0; j < UL_LEN * 2; j++) {
        p1 = (ulv *) bufa;
        p2 = (ulv *) bufb;
        out_test_setting(j);
        for (i = 0; i < count; i++) {
            ul expected;
            if (j < UL_LEN) { /* Walk it up. */
                expected = ONE << j;
            } else { /* Walk it back down. */
                expected = ONE << (UL_LEN * 2 - j - 1);
            }
            rampage_expect(i, expected);
            *p1++ = *p2++ = expected;
        }
        out_test_testing(j);
        if (compare_with_injection(bufa, bufb, count, 5)) {
            return -1;
        }
    }
    out_test_end();
    return 0;
}

int test_walkbits1_comparison(ulv *bufa, ulv *bufb, size_t count) {
    ulv *p1 = bufa;
    ulv *p2 = bufb;
    unsigned int j;
    size_t i;

    out_test_start();
    for (j = 0; j < UL_LEN * 2; j++) {
        p1 = (ulv *) bufa;
        p2 = (ulv *) bufb;
        out_test_setting(j);
        for (i = 0; i < count; i++) {
            ul expected;
            if (j < UL_LEN) { /* Walk it up. */
                expected = UL_ONEBITS ^ (ONE << j);
            } else { /* Walk it back down. */
                expected = UL_ONEBITS ^ (ONE << (UL_LEN * 2 - j - 1));
            }
            rampage_expect(i, expected);
            *p1++ = *p2++ = expected;
        }
        out_test_testing(j);
        if (compare_regions(bufa, bufb, count)) {
            return -1;
        }
    }
    out_test_end();
    return 0;
}

int test_bitspread_comparison(ulv *bufa, ulv *bufb, size_t count) {
    ulv *p1 = bufa;
    ulv *p2 = bufb;
    unsigned int j;
    size_t i;

    out_test_start();
    for (j = 0; j < UL_LEN * 2; j++) {
        p1 = (ulv *) bufa;
        p2 = (ulv *) bufb;
        out_test_setting(j);
        for (i = 0; i < count; i++) {
            ul expected;
            if (j < UL_LEN) { /* Walk it up. */
                expected = (i % 2 == 0)
                    ? (ONE << j) | (ONE << (j + 2))
                    : UL_ONEBITS ^ ((ONE << j)
                                    | (ONE << (j + 2)));
            } else { /* Walk it back down. */
                expected = (i % 2 == 0)
                    ? (ONE << (UL_LEN * 2 - 1 - j)) | (ONE << (UL_LEN * 2 + 1 - j))
                    : UL_ONEBITS ^ (ONE << (UL_LEN * 2 - 1 - j)
                                    | (ONE << (UL_LEN * 2 + 1 - j)));
            }
            rampage_expect(i, expected);
            *p1++ = *p2++ = expected;
        }
        out_test_testing(j);
        if (compare_regions(bufa, bufb, count)) {
            return -1;
        }
    }
    out_test_end();
    return 0;
}

int test_bitflip_comparison(ulv *bufa, ulv *bufb, size_t count) {
    ulv *p1 = bufa;
    ulv *p2 = bufb;
    unsigned int j, k;
    ul q;
    size_t i;

    out_test_start();
    for (k = 0; k < UL_LEN; k++) {
        q = ONE << k;
        for (j = 0; j < 8; j++) {
            q = ~q;
            out_test_setting(k * 8 + j);
            p1 = (ulv *) bufa;
            p2 = (ulv *) bufb;
            for (i = 0; i < count; i++) {
                ul expected = (i % 2) == 0 ? q : ~q;
                rampage_expect(i, expected);
                *p1++ = *p2++ = expected;
            }
            out_test_testing(k * 8 + j);
            fflush(stdout);
            if (compare_regions(bufa, bufb, count)) {
                return -1;
            }
        }
    }
    out_test_end();
    return 0;
}

#ifdef TEST_NARROW_WRITES
int test_8bit_wide_random(ulv* bufa, ulv* bufb, size_t count) {
    u8v *p1, *t;
    ulv *p2;
    int attempt;
    unsigned int b;
    size_t i;

    out_wheel_start();
    for (attempt = 0; attempt < 2;  attempt++) {
        if (attempt & 1) {
            p1 = (u8v *) bufa;
            p2 = bufb;
        } else {
            p1 = (u8v *) bufb;
            p2 = bufa;
        }
        for (i = 0; i < count; i++) {
            t = mword8.bytes;
            *p2++ = mword8.val = rand_ul();
            rampage_expect(i, mword8.val);
            for (b=0; b < UL_LEN/8; b++) {
                *p1++ = *t++;
            }
            out_wheel_advance(i);
        }
        if (compare_with_injection(bufa, bufb, count, 7)) {
            return -1;
        }
    }
    out_wheel_end();
    return 0;
}

int test_16bit_wide_random(ulv* bufa, ulv* bufb, size_t count) {
    u16v *p1, *t;
    ulv *p2;
    int attempt;
    unsigned int b;
    size_t i;

    out_wheel_start();
    for (attempt = 0; attempt < 2; attempt++) {
        if (attempt & 1) {
            p1 = (u16v *) bufa;
            p2 = bufb;
        } else {
            p1 = (u16v *) bufb;
            p2 = bufa;
        }
        for (i = 0; i < count; i++) {
            t = mword16.u16s;
            *p2++ = mword16.val = rand_ul();
            rampage_expect(i, mword16.val);
            for (b = 0; b < UL_LEN/16; b++) {
                *p1++ = *t++;
            }
            out_wheel_advance(i);
        }
        if (compare_regions(bufa, bufb, count)) {
            return -1;
        }
    }
    out_wheel_end();
    return 0;
}
#endif


