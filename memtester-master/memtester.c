/*
 * memtester version 4
 *
 * Very simple but very effective user-space memory tester.
 * Originally by Simon Kirby <sim@stormix.com> <sim@neato.org>
 * Version 2 by Charles Cazabon <charlesc-memtester@pyropus.ca>
 * Version 3 not publicly released.
 * Version 4 rewrite:
 * Copyright (C) 2004-2020 Charles Cazabon <charlesc-memtester@pyropus.ca>
 * Licensed under the terms of the GNU General Public License version 2 (only).
 * See the file COPYING for details.
 *
 */

#define __version__ "4.5.1"

#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/mman.h>
#include <unistd.h>
#include <fcntl.h>
#include <string.h>
#include <errno.h>
#include <stdint.h>
//LZU CHANGE
#include <limits.h>
#include "types.h"
#include "sizes.h"
#include "memtester.h"
#include "tests.h"
#include "output.h"

#define EXIT_FAIL_NONSTARTER    0x01
#define EXIT_FAIL_ADDRESSLINES  0x02
#define EXIT_FAIL_OTHERTEST     0x04

//ba
/* 由 tests.c 提供的全局变量 */
extern uintptr_t inject_bufa_start;
extern size_t inject_pagesize;
extern ssize_t inject_page_rel;
extern int inject_kind;
extern int inject_once;


struct test tests[] = {
    { "Random Value", test_random_value },
    { "Compare XOR", test_xor_comparison },
    { "Compare SUB", test_sub_comparison },
    { "Compare MUL", test_mul_comparison },
    { "Compare DIV",test_div_comparison },
    { "Compare OR", test_or_comparison },
    { "Compare AND", test_and_comparison },
    { "Sequential Increment", test_seqinc_comparison },
    { "Solid Bits", test_solidbits_comparison },
    { "Block Sequential", test_blockseq_comparison },
    { "Checkerboard", test_checkerboard_comparison },
    { "Bit Spread", test_bitspread_comparison },
    { "Bit Flip", test_bitflip_comparison },
    { "Walking Ones", test_walkbits1_comparison },
    { "Walking Zeroes", test_walkbits0_comparison },
#ifdef TEST_NARROW_WRITES
    { "8-bit Writes", test_8bit_wide_random },
    { "16-bit Writes", test_16bit_wide_random },
#endif
    { NULL, NULL }
};

static const char *inject_kind_names[] = {
    "不注入",                        /* 0 */
    "test_stuck_address：检测地址线故障，写入地址值后读回，确认每个地址单元存的是自己的地址而非别人的数据",            /* 1 */
    "Compare XOR： 检测相邻内存单元间的耦合干扰，用互补图案交叉写入后比较",           /* 2 */
    "Solid Bits： 检测位的“粘连”故障（stuck-at-0/1），全写 0 或全写 1 后读回验证",     /* 3 */
    "Checkerboard： 检测相邻位/单元间的串扰，写入棋盘格图案（0101…/1010…）验证位间独立性",  /* 4 */
    "Walking Zeroes： 检测地址/数据线短路，单个 0 在全 1 背景中逐位移动，验证每根线互相独立",     /* 5 */
    "Compare OR：存储单元写入保持能力异常、位间耦合，用 OR 运算图案检测不同类型的耦合错误",     /* 6 */
#ifdef TEST_NARROW_WRITES
    "8-bit Writes：检测窄写路径的掩码逻辑故障，验证按字节写入时不会误修改相邻字节",         /* 7*/
#endif
};

#define INJECT_KIND_MAX (sizeof(inject_kind_names) / sizeof(inject_kind_names[0]))



/* Sanity checks and portability helper macros. */
#ifdef _SC_VERSION
void check_posix_system(void) {
    if (sysconf(_SC_VERSION) < 198808L) {
        fprintf(stderr, "A POSIX system is required.  Don't be surprised if "
            "this craps out.\n");
        fprintf(stderr, "_SC_VERSION is %lu\n", sysconf(_SC_VERSION));
    }
}
#else
#define check_posix_system()
#endif

#ifdef _SC_PAGE_SIZE
int memtester_pagesize(void) {
    int pagesize = sysconf(_SC_PAGE_SIZE);
    if (pagesize == -1) {
        perror("get page size failed");
        exit(EXIT_FAIL_NONSTARTER);
    }
    printf("pagesize is %ld\n", (long) pagesize);
    return pagesize;
}
#else
int memtester_pagesize(void) {
    printf("sysconf(_SC_PAGE_SIZE) not supported; using pagesize of 8192\n");
    return 8192;
}
#endif

/* Some systems don't define MAP_LOCKED.  Define it to 0 here
   so it's just a no-op when ORed with other constants. */
#ifndef MAP_LOCKED
  #define MAP_LOCKED 0
#endif

/* Function declarations */
void usage(char *me);

/* Global vars - so tests have access to this information */
int use_phys = 0;
off_t physaddrbase = 0;

/* Function definitions */
void usage(char *me) {
    //LZU CHANGE
    fprintf(stderr, "\n"
            "Usage: %s [-p physaddrbase [-d device] [-u]] [-i page] [-c type] <mem>[B|K|M|G] [loops]\n"
            "       %s -F mapped_fd -R result_fd -S session_id [-i page] [-c type] <mem>B 1\n",
            me,
            me);
    exit(EXIT_FAIL_NONSTARTER);
}

//LZU CHANGE
static int parse_fd(const char *value) {
    char *end;
    long fd;

    errno = 0;
    fd = strtol(value, &end, 10);
    if (errno || *value == '\0' || *end != '\0' || fd < 0 || fd > INT_MAX ||
        fcntl((int)fd, F_GETFD) == -1) {
        fprintf(stderr, "invalid inherited file descriptor: %s\n", value);
        exit(EXIT_FAIL_NONSTARTER);
    }
    return (int)fd;
}

static int rampage_test_id(size_t index) {
    if (tests[index].fp == test_xor_comparison) return 2;
    if (tests[index].fp == test_solidbits_comparison) return 3;
    if (tests[index].fp == test_checkerboard_comparison) return 4;
    if (tests[index].fp == test_walkbits0_comparison) return 5;
    if (tests[index].fp == test_or_comparison) return 6;
#ifdef TEST_NARROW_WRITES
    if (tests[index].fp == test_8bit_wide_random) return 7;
#endif
    return 8 + (int)index;
}

static int write_failures(FILE *result, int type) {
    size_t i;

    for (i = 0; i < rampage_failure_count; i++) {
        const struct rampage_failure *failure = &rampage_failures[i];
        fprintf(result, "BAD %d %zu %c %lu %lu\n", type, failure->offset,
                failure->side, failure->expected, failure->observed);
    }
    return !rampage_failure_count || fflush(result) != 0;
}

static int run_rampage_pages(int mapped_fd, int result_fd, unsigned long long session_id,
                             size_t bytes, size_t pagesize, ul testmask) {
    size_t page_index, page_count = bytes / pagesize;
    size_t count = (pagesize / 2) / sizeof(ul);
    void *mapping;
    FILE *result;
    int exit_code = 0;

    mapping = mmap(NULL, bytes, PROT_READ | PROT_WRITE, MAP_SHARED, mapped_fd, 0);
    if (mapping == MAP_FAILED) {
        perror("RAMpage mmap failed");
        return EXIT_FAIL_NONSTARTER;
    }
    result = fdopen(dup(result_fd), "w");
    if (!result) {
        perror("RAMpage result fd failed");
        munmap(mapping, bytes);
        return EXIT_FAIL_NONSTARTER;
    }
    rampage_expected = malloc(pagesize);
    if (!rampage_expected) {
        perror("RAMpage expected-value allocation failed");
        fclose(result);
        munmap(mapping, bytes);
        return EXIT_FAIL_NONSTARTER;
    }
    rampage_expected_count = pagesize / sizeof(ul);

    rampage_test_base = (uintptr_t)mapping;
    inject_bufa_start = (uintptr_t)mapping;
    inject_pagesize = pagesize;
    rampage_result = result;
    fprintf(result, "RAMPAGE_RESULT_V3 %llu %zu\n", session_id, page_count);
    if (fflush(result) != 0) {
        exit_code = EXIT_FAIL_NONSTARTER;
        goto out;
    }

    for (page_index = 0; page_index < page_count; page_index++) {
        ulv *bufa = (ulv *)((char *)mapping + page_index * pagesize);
        ulv *bufb = (ulv *)((char *)bufa + pagesize / 2);
        ul i;

        printf("Page %zu/%zu:\n", page_index + 1, page_count);
        printf("  %-20s: ", "Stuck Address");
        fflush(stdout);
        rampage_reset_failure();
        if (!test_stuck_address(bufa, pagesize / sizeof(ul))) {
            printf("ok\n");
        } else {
            exit_code |= EXIT_FAIL_ADDRESSLINES;
            if (write_failures(result, 1)) {
                exit_code |= EXIT_FAIL_NONSTARTER;
                break;
            }
            continue;
        }

        for (i = 0; tests[i].name; i++) {
            if (testmask && !((1UL << i) & testmask)) {
                continue;
            }
            memset((void *)bufa, 255, pagesize);
            printf("  %-20s: ", tests[i].name);
            fflush(stdout);
            rampage_reset_failure();
            if (!tests[i].fp(bufa, bufb, count)) {
                printf("ok\n");
            } else {
                exit_code |= EXIT_FAIL_OTHERTEST;
                if (write_failures(result, rampage_test_id(i)))
                    exit_code |= EXIT_FAIL_NONSTARTER;
                break;
            }
            fflush(stdout);
        }

        if (exit_code & EXIT_FAIL_NONSTARTER)
            break;
        printf("\n");
        fflush(stdout);
    }

out:
    if (munmap(mapping, bytes) != 0) {
        perror("RAMpage unmap failed");
        exit_code |= EXIT_FAIL_NONSTARTER;
    }
    if (!(exit_code & EXIT_FAIL_NONSTARTER) && !ferror(result)) {
        if (rampage_injection_offset == SIZE_MAX)
            fprintf(result, "INJECT NONE\n");
        fprintf(result, "END\n");
    }
    if (fclose(result) != 0) {
        perror("RAMpage result close failed");
        exit_code |= EXIT_FAIL_NONSTARTER;
    }
    rampage_result = NULL;
    free(rampage_expected);
    rampage_expected = NULL;
    rampage_expected_count = 0;
    return exit_code;
}

int main(int argc, char **argv) {
    ul loops, loop, i;
    size_t pagesize, wantraw, wantmb, wantbytes, wantbytes_orig, bufsize,
         halflen, count;
    char *memsuffix, *addrsuffix, *loopsuffix;
    ptrdiff_t pagesizemask;
    void volatile *buf, *aligned;
    ulv *bufa, *bufb;
    int do_mlock = 1, done_mem = 0;
    int exit_code = 0;
    int memfd, opt, memshift;
    //LZU CHANGE
    int rampage_fd = -1, result_fd = -1;
    unsigned long long rampage_session_id = 0;
    size_t maxbytes = -1; /* addressable memory, in bytes */
    size_t maxmb = (maxbytes >> 20) + 1; /* addressable memory, in MB */
    /* Device to mmap memory from with -p, default is normal core */
    char *device_name = "/dev/mem";
    struct stat statbuf;
    int device_specified = 0;
    char *env_testmask = 0;
    ul testmask = 0;
    int o_flags = O_RDWR | O_SYNC;

    out_initialize();

    printf("memtester version " __version__ " (%d-bit)\n", UL_LEN);
    printf("Copyright (C) 2001-2020 Charles Cazabon.\n");
    printf("Licensed under the GNU General Public License version 2 (only).\n");
    printf("\n");
    check_posix_system();
    pagesize = memtester_pagesize();
    pagesizemask = (ptrdiff_t) ~(pagesize - 1);
    printf("pagesizemask is 0x%tx\n", pagesizemask);

    /* If MEMTESTER_TEST_MASK is set, we use its value as a mask of which
       tests we run.
     */
    if (env_testmask = getenv("MEMTESTER_TEST_MASK")) {
        errno = 0;
        testmask = strtoul(env_testmask, 0, 0);
        if (errno) {
            fprintf(stderr, "error parsing MEMTESTER_TEST_MASK %s: %s\n",
                    env_testmask, strerror(errno));
            usage(argv[0]); /* doesn't return */
        }
        printf("using testmask 0x%lx\n", testmask);
    }

    //LZU CHANGE
    while ((opt = getopt(argc, argv, "p:d:ui:c:F:R:S:")) != -1) {
        switch (opt) {
            case 'p':
                errno = 0;
                physaddrbase = (off_t) strtoull(optarg, &addrsuffix, 16);
                if (errno != 0) {
                    fprintf(stderr,
                            "failed to parse physaddrbase arg; should be hex "
                            "address (0x123...)\n");
                    usage(argv[0]); /* doesn't return */
                }
                if (*addrsuffix != '\0') {
                    /* got an invalid character in the address */
                    fprintf(stderr,
                            "failed to parse physaddrbase arg; should be hex "
                            "address (0x123...)\n");
                    usage(argv[0]); /* doesn't return */
                }
                if (physaddrbase & (pagesize - 1)) {
                    fprintf(stderr,
                            "bad physaddrbase arg; does not start on page "
                            "boundary\n");
                    usage(argv[0]); /* doesn't return */
                }
                /* okay, got address */
                use_phys = 1;
                break;
            case 'd':
                if (stat(optarg,&statbuf)) {
                    fprintf(stderr, "can not use %s as device: %s\n", optarg,
                            strerror(errno));
                    usage(argv[0]); /* doesn't return */
                } else {
                    if (!S_ISCHR(statbuf.st_mode)) {
                        fprintf(stderr, "can not mmap non-char device %s\n",
                                optarg);
                        usage(argv[0]); /* doesn't return */
                    } else {
                        device_name = optarg;
                        device_specified = 1;
                    }
                }
                break;
            case 'u':
		o_flags &= ~O_SYNC;
		break;
            case 'i':
                inject_page_rel = atoi(optarg);
                if (inject_page_rel >= 0) {
                    inject_once = 1;
                    printf("命令行指定错误注入页：%zd\n", inject_page_rel);
                } else {
                    printf("未启用错误注入（命令行）\n");
                }
                break;
            case 'c':
                inject_kind = atoi(optarg);
                if (inject_kind > 0 && (size_t)inject_kind < INJECT_KIND_MAX) {
                    printf("命令行指定注入类型：%d (%s)\n", inject_kind, inject_kind_names[inject_kind]);
                } else {
                    inject_kind = 0;
                    printf("不注入错误 \n");
                }
                break;
            //LZU CHANGE
            case 'F':
                rampage_fd = parse_fd(optarg);
                break;
            case 'R':
                result_fd = parse_fd(optarg);
                break;
            case 'S': {
                char *end;
                errno = 0;
                rampage_session_id = strtoull(optarg, &end, 10);
                if (errno || !*optarg || *end || !rampage_session_id) usage(argv[0]);
                break;
            }
            default: /* '?' */
                usage(argv[0]); /* doesn't return */
        }
    }

    if (device_specified && !use_phys) {
        fprintf(stderr,
                "for mem device, physaddrbase (-p) must be specified\n");
        usage(argv[0]); /* doesn't return */
    }

    if (optind >= argc) {
        fprintf(stderr, "need memory argument, in MB\n");
        usage(argv[0]); /* doesn't return */
    }

    errno = 0;
    wantraw = (size_t) strtoul(argv[optind], &memsuffix, 0);
    if (errno != 0) {
        fprintf(stderr, "failed to parse memory argument");
        usage(argv[0]); /* doesn't return */
    }
    switch (*memsuffix) {
        case 'G':
        case 'g':
            memshift = 30; /* gigabytes */
            break;
        case 'M':
        case 'm':
            memshift = 20; /* megabytes */
            break;
        case 'K':
        case 'k':
            memshift = 10; /* kilobytes */
            break;
        case 'B':
        case 'b':
            memshift = 0; /* bytes*/
            break;
        case '\0':  /* no suffix */
            memshift = 20; /* megabytes */
            break;
        default:
            /* bad suffix */
            usage(argv[0]); /* doesn't return */
    }
    wantbytes_orig = wantbytes = ((size_t) wantraw << memshift);
    wantmb = (wantbytes_orig >> 20);
    optind++;
    if (wantmb > maxmb) {
        fprintf(stderr, "This system can only address %llu MB.\n", (ull) maxmb);
        exit(EXIT_FAIL_NONSTARTER);
    }
    if (wantbytes < pagesize) {
        fprintf(stderr, "bytes %ld < pagesize %ld -- memory argument too large?\n",
                wantbytes, pagesize);
        exit(EXIT_FAIL_NONSTARTER);
    }

    if (optind >= argc) {
        loops = 0;
    } else {
        errno = 0;
        loops = strtoul(argv[optind], &loopsuffix, 0);
        if (errno != 0) {
            fprintf(stderr, "failed to parse number of loops");
            usage(argv[0]); /* doesn't return */
        }
        if (*loopsuffix != '\0') {
            fprintf(stderr, "loop suffix %c\n", *loopsuffix);
            usage(argv[0]); /* doesn't return */
        }
    }

    //LZU CHANGE
    if (rampage_fd >= 0 || result_fd >= 0) {
        if (rampage_fd < 0 || result_fd < 0 || rampage_fd == result_fd ||
            !rampage_session_id ||
            use_phys || device_specified || loops != 1 ||
            wantbytes % pagesize != 0 || pagesize % (2 * sizeof(ul)) != 0 ||
            (inject_page_rel >= 0 && ((size_t)inject_page_rel >= wantbytes / pagesize ||
                                      inject_kind < 1 || inject_kind > 7))) {
            fprintf(stderr, "invalid RAMpage mapping arguments\n");
            exit(EXIT_FAIL_NONSTARTER);
        }
        exit(run_rampage_pages(rampage_fd, result_fd, rampage_session_id, wantbytes,
                               pagesize, testmask));
    }

    printf("want %lluMB (%llu bytes)\n", (ull) wantmb, (ull) wantbytes);
    buf = NULL;

    if (use_phys) {
        memfd = open(device_name, o_flags);
        if (memfd == -1) {
            fprintf(stderr, "failed to open %s for physical memory: %s\n",
                    device_name, strerror(errno));
            exit(EXIT_FAIL_NONSTARTER);
        }
        buf = (void volatile *) mmap(0, wantbytes, PROT_READ | PROT_WRITE,
                                     MAP_SHARED | MAP_LOCKED, memfd,
                                     physaddrbase);
        if (buf == MAP_FAILED) {
            fprintf(stderr, "failed to mmap %s for physical memory: %s\n",
                    device_name, strerror(errno));
            exit(EXIT_FAIL_NONSTARTER);
        }

        if (mlock((void *) buf, wantbytes) < 0) {
            fprintf(stderr, "failed to mlock mmap'ed space\n");
            do_mlock = 0;
        }

        bufsize = wantbytes; /* accept no less */
        aligned = buf;
        done_mem = 1;
    }

    while (!done_mem) {
        while (!buf && wantbytes) {
            buf = (void volatile *) malloc(wantbytes);
            if (!buf) wantbytes -= pagesize;
        }
        bufsize = wantbytes;
        printf("got  %lluMB (%llu bytes)", (ull) wantbytes >> 20,
            (ull) wantbytes);
        fflush(stdout);
        if (do_mlock) {
            printf(", trying mlock ...");
            fflush(stdout);
            if ((size_t) buf % pagesize) {
                /* printf("aligning to page -- was 0x%tx\n", buf); */
                aligned = (void volatile *) ((size_t) buf & pagesizemask) + pagesize;
                /* printf("  now 0x%tx -- lost %d bytes\n", aligned,
                 *      (size_t) aligned - (size_t) buf);
                 */
                bufsize -= ((size_t) aligned - (size_t) buf);
            } else {
                aligned = buf;
            }
            /* Try mlock */
            if (mlock((void *) aligned, bufsize) < 0) {
                switch(errno) {
                    case EAGAIN: /* BSDs */
                        printf("over system/pre-process limit, reducing...\n");
                        free((void *) buf);
                        buf = NULL;
                        wantbytes -= pagesize;
                        break;
                    case ENOMEM:
                        printf("too many pages, reducing...\n");
                        free((void *) buf);
                        buf = NULL;
                        wantbytes -= pagesize;
                        break;
                    case EPERM:
                        printf("insufficient permission.\n");
                        printf("Trying again, unlocked:\n");
                        do_mlock = 0;
                        free((void *) buf);
                        buf = NULL;
                        wantbytes = wantbytes_orig;
                        break;
                    default:
                        printf("failed for unknown reason.\n");
                        do_mlock = 0;
                        done_mem = 1;
                }
            } else {
                printf("locked.\n");
                done_mem = 1;
            }
        } else {
            done_mem = 1;
            printf("\n");
        }
    }

    if (!do_mlock) fprintf(stderr, "Continuing with unlocked memory; testing "
                           "will be slower and less reliable.\n");

    /* Do alighnment here as well, as some cases won't trigger above if you
       define out the use of mlock() (cough HP/UX 10 cough). */
    if ((size_t) buf % pagesize) {
        /* printf("aligning to page -- was 0x%tx\n", buf); */
        aligned = (void volatile *) ((size_t) buf & pagesizemask) + pagesize;
        /* printf("  now 0x%tx -- lost %d bytes\n", aligned,
         *      (size_t) aligned - (size_t) buf);
         */
        bufsize -= ((size_t) aligned - (size_t) buf);
    } else {
        aligned = buf;
    }

    halflen = bufsize / 2;
    count = halflen / sizeof(ul);
    bufa = (ulv *) aligned;
    bufb = (ulv *) ((size_t) aligned + halflen);
    /* 设置全局变量，让 test_or_comparison 能访问 */
    inject_bufa_start = (uintptr_t)bufa;
    inject_pagesize = pagesize;

    /* 打印页范围 */
    uintptr_t bufa_start_addr = (uintptr_t)bufa;
    uintptr_t bufa_end_addr   = (uintptr_t)bufa + halflen - 1;
    uintptr_t bufb_start_addr = (uintptr_t)bufb;
    uintptr_t bufb_end_addr   = (uintptr_t)bufb + halflen - 1;

    printf("\n=== Memory Page Info ===\n");
    printf("Page size: %zu bytes\n", pagesize);
    printf("bufa pages: [%zu .. %zu]\n",
           bufa_start_addr / pagesize, bufa_end_addr / pagesize);
    printf("bufb pages: [%zu .. %zu]\n",
           bufb_start_addr / pagesize, bufb_end_addr / pagesize);
    printf("=========================\n");

    /* 交互式输入注入页号 */
    // char line[64];
    // printf("请输入要注入错误的页号（相对 bufa 起始页，输入 -1 表示不注入）: ");
    // fflush(stdout);
    // if (fgets(line, sizeof(line), stdin)) {
    //     inject_page_rel = atoi(line);
    //     if (inject_page_rel >= 0) {
    //         inject_enabled = 1;
    //         inject_once = 1;
    //         printf("将在 bufa 的第 %zd 页注入一次错误。\n", inject_page_rel);
    //     } else {
    //         printf("未启用错误注入。\n");
    //     }
    // }

    for(loop=1; ((!loops) || loop <= loops); loop++) {
        printf("Loop %lu", loop);
        if (loops) {
            printf("/%lu", loops);
        }
        printf(":\n");
        printf("  %-20s: ", "Stuck Address");
        fflush(stdout);
        if (!test_stuck_address(aligned, bufsize / sizeof(ul))) {
             printf("ok\n");
        } else {
            exit_code |= EXIT_FAIL_ADDRESSLINES;
        }
        for (i=0;;i++) {
            if (!tests[i].name) break;
            /* If using a custom testmask, only run this test if the
               bit corresponding to this test was set by the user.
             */
            if (testmask && (!((1 << i) & testmask))) {
                continue;
            }
            printf("  %-20s: ", tests[i].name);
            fflush(stdout);
            if (!tests[i].fp(bufa, bufb, count)) {
                printf("ok\n");
            } else {
                exit_code |= EXIT_FAIL_OTHERTEST;
            }
            fflush(stdout);
            /* clear buffer */
            memset((void *) buf, 255, wantbytes);
        }
        printf("\n");
        fflush(stdout);
    }
    if (do_mlock) munlock((void *) aligned, bufsize);
    printf("Done.\n");
    fflush(stdout);
    exit(exit_code);
}


