#ifndef ARCHREACTOR_EXAMPLES_COMMON_H
#define ARCHREACTOR_EXAMPLES_COMMON_H

static inline void print_string(const char* str) {
    asm volatile (
        "mv a0, %0\n\t"
        "li a7, 4\n\t"
        "ecall"
        :
        : "r"(str)
        : "a0", "a7"
    );
}

static inline void print_int(int value) {
    asm volatile (
        "mv a0, %0\n\t"
        "li a7, 1\n\t"
        "ecall"
        :
        : "r"(value)
        : "a0", "a7"
    );
}

static inline void program_exit(void) {
    asm volatile (
        "li a7, 10\n\t"
        "ecall"
        :
        :
        : "a7"
    );
}

static inline void print_result(int ok) {
    if (ok) {
        print_string("PASS\n");
    } else {
        print_string("FAIL\n");
    }
}

#endif
