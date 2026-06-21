#include "common.h"

int __attribute__((noinline)) square(int value) {
    return value * value;
}

int main(void) {
    print_string("05 function call\n");

    int value = 12;
    int result = square(value);

    print_result(result == 144);
    program_exit();
    return 0;
}
