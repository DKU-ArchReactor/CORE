#include "common.h"

int main(void) {
    print_string("04 branch flush\n");

    int sum = 0;
    for (int i = 0; i < 4; i++) {
        sum += i;
    }

    print_result(sum == 6);
    program_exit();
    return 0;
}
